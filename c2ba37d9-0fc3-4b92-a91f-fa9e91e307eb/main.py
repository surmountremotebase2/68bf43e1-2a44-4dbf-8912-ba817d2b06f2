from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):

    """
    Ultra-Conservative Clenow-style dynamic tactical allocation with volatility targeting
    and a hysteresis-buffered trend circuit breaker.
    Long only, no leverage, daily bars, always invested (BIL is the cash holding).

    Risk profile: Capital preservation first (target 10y risk score 1.0 - 1.5).
      Equity band: 12% to 22%. Minimum cash buffer: 20% BIL.
      Momentum multiplier: 0.75x to 1.20x combined with 60-day inverse-volatility tilt.
      Portfolio volatility cap: ex-ante annualized volatility capped at 3.2% via BIL scaling.
      abs_gate ON: an ETF with negative Clenow Momentum goes to BIL.
      Trend circuit breaker: when SPY closes >0.5% below its 200-day average, equity is cut to 0%
      and moved to BIL; re-enters when SPY closes >0.5% above its 200-day average.

    Source: Andreas Clenow, "Technical Asset Allocation" (CMT Association, 2025).
    Clenow Momentum = ((exp(slope)^252 - 1) * 100) * R^2 on a 90-day log-price regression.

    Guardrails (fail closed, keep holdings): sum <= 1, no negative weights, single ETF <= 15%,
    equity inside the band (floor relaxed by abs_gate and by the trend breaker).
    History: needs 210 bars. Missing data never raises: every skip is logged.
    """

    def __init__(self):
        # Universe
        self.equity = ["VT", "IXN", "GSLC", "VIG", "MTUM", "IMTM", "XLV", "XLU", "XLE", "XLP", "QQQ", "RSP", "EFA", "IJT"]
        self.bonds = ["GLD", "SHY", "AGG", "IEF", "BND", "TIP", "TLT"]
        self.cash = "BIL"
        self.trading = self.equity + self.bonds + [self.cash]

        # Base (strategic) weights: 32% equity / 48% defensive / 20% minimum cash
        self.base_equity = 0.32
        self.base_bonds = 0.48
        self.cash_min = 0.20

        # Clenow Momentum, inverse-volatility tilt, and portfolio volatility target
        self.mom_window = 90
        self.vol_window = 60
        self.m_min = 0.75
        self.m_max = 1.20
        self.target_vol = 0.032  # 3.2% annualized ex-ante volatility cap

        # Risk profile
        self.use_band = True
        self.e_floor = 0.12
        self.e_ceil = 0.22
        self.max_weight = 0.15
        self.abs_gate = True

        # Trend circuit breaker with hysteresis buffer
        self.use_trend = True
        self.trend_ticker = "SPY"
        self.trend_window = 200
        self.trend_band = 0.005  # 0.5% hysteresis band around 200-day SMA to prevent whipsaws
        self.trend_keep = 0.00   # full equity exit during confirmed downtrends (0% kept, 100% cut)

        # Monthly rebalance
        self.rebalance_months = 1

        self.min_bars = 210
        self.bars = 260

        self.base = {t: self.base_equity / len(self.equity) for t in self.equity}
        # Tilted toward short-duration fixed income to limit rate-shock drawdowns
        self.base.update({"SHY": 0.160, "AGG": 0.120, "BND": 0.090, "IEF": 0.030,
                          "TIP": 0.040, "TLT": 0.015, "GLD": 0.025})  # sums to 0.48

    @property
    def assets(self):
        return self.trading + [self.trend_ticker]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # price data only

    # ---------- helpers ----------
    @staticmethod
    def _stamp(bar):
        for v in bar.values():
            return str(v["date"])
        return ""

    def _period(self, bar):
        stamp = self._stamp(bar)
        try:
            return (int(stamp[:4]) * 12 + int(stamp[5:7]) - 1) // self.rebalance_months
        except ValueError:
            return -1

    def _frame(self, rows):
        return pd.DataFrame({t: [bar[t]["close"] if t in bar else float("nan") for bar in rows]
                             for t in self.trading})

    @staticmethod
    def _clenow(closes):
        """Annualised exponential regression slope (%) times R^2, on the given closes."""
        y = np.log(np.asarray(closes, dtype=float))
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float(((y - (slope * x + intercept)) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
        return (math.exp(slope) ** 252 - 1.0) * 100.0 * r2

    def _risk_off(self, rows):
        """Stateless hysteresis-buffered trend check on SPY vs 200-day SMA. None if data missing."""
        n = self.trend_window
        lookback = min(len(rows), n + 50)
        if lookback < n:
            return None
        sub = rows[-lookback:]
        c = [bar[self.trend_ticker]["close"] if self.trend_ticker in bar else float("nan") for bar in sub]
        if any(x != x for x in c):
            return None
        arr = np.asarray(c, dtype=float)
        sma_0 = arr[:n].mean()
        if sma_0 <= 0:
            return None
        state = bool(arr[n - 1] < sma_0)
        for i in range(n, len(arr)):
            sma_i = arr[i - n + 1:i + 1].mean()
            if not state and arr[i] < sma_i * (1.0 - self.trend_band):
                state = True
            elif state and arr[i] > sma_i * (1.0 + self.trend_band):
                state = False
        return state

    def _derisk(self, w):
        """Keep trend_keep (0%) of each equity weight, move the rest (100%) to BIL."""
        out = dict(w)
        cut = sum(out[t] for t in self.equity) * (1.0 - self.trend_keep)
        for t in self.equity:
            out[t] *= self.trend_keep
        out[self.cash] += cut
        return out

    def _target(self, df):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        scored = self.equity + self.bonds
        n = self.mom_window
        if len(df) < n:
            return None, {}
        win = df.iloc[-n:]
        if win[scored].isna().any().any() or pd.isna(df[self.cash].iloc[-1]):
            return None, {}
        if (win[scored] <= 0).any().any():
            return None, {}

        cm = {t: self._clenow(win[t].values) for t in scored}

        # Realized volatility over vol_window for inverse-vol weighting and vol targeting
        rets = np.log(win[scored].iloc[-self.vol_window:]).diff().dropna()
        ann_vol = rets.std() * math.sqrt(252.0)

        # Momentum multiplier combined with square-root inverse-volatility tilt within each sleeve
        mult = {}
        for group in (self.equity, self.bonds):
            rk = pd.Series({t: cm[t] for t in group}).rank(method="average")
            for t in group:
                r = (rk[t] - 1.0) / (len(group) - 1.0)
                mom_m = self.m_min * (self.m_max / self.m_min) ** r
                inv_vol = (1.0 / max(float(ann_vol[t]), 0.04)) ** 0.5
                mult[t] = mom_m * inv_vol

        # Normalize within each sleeve first so strategic sleeve weights are preserved before banding
        risky = 1.0 - self.cash_min
        raw = {}
        for group, sleeve_base in ((self.equity, self.base_equity), (self.bonds, self.base_bonds)):
            g_raw = {t: self.base[t] * mult[t] for t in group}
            g_sum = sum(g_raw.values())
            for t in group:
                raw[t] = (g_raw[t] / g_sum) * sleeve_base if g_sum > 0 else 0.0

        tot = sum(raw.values())
        w = {t: raw[t] / tot * risky for t in scored} if tot > 0 else {t: 0.0 for t in scored}

        # Equity band: rescale both sleeves to the nearest bound
        if self.use_band:
            e = sum(w[t] for t in self.equity)
            e2 = min(max(e, self.e_floor), self.e_ceil)
            if abs(e2 - e) > 1e-12 and e > 0 and (risky - e) > 0:
                for t in self.equity:
                    w[t] *= e2 / e
                for t in self.bonds:
                    w[t] *= (risky - e2) / (risky - e)

        # Absolute gate: negative Clenow Momentum goes to BIL
        n_neg = sum(1 for t in scored if cm[t] < 0)
        if self.abs_gate:
            for t in scored:
                if cm[t] < 0:
                    w[t] = 0.0

        # Cap single-asset concentration
        for t in scored:
            if w[t] > self.max_weight:
                w[t] = self.max_weight

        # Ex-ante portfolio volatility target overlay: scale risky basket into BIL if vol > target_vol
        w_vec = np.array([w[t] for t in scored], dtype=float)
        if w_vec.sum() > 0 and len(rets) > 10:
            cov_ann = rets.cov().values * 252.0
            port_vol = float(np.sqrt(np.dot(w_vec, np.dot(cov_ann, w_vec))))
            if port_vol > self.target_vol and port_vol > 0:
                vol_scale = self.target_vol / port_vol
                for t in scored:
                    w[t] *= vol_scale

        tgt = {a: 0.0 for a in self.trading}
        tgt.update(w)
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity=sum(w[t] for t in self.equity), n_neg=n_neg)

    def _valid(self, w, relax=False):
        e = sum(w[c] for c in self.equity)
        ok = (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
              and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9)
        if self.use_band:
            ok = ok and e <= self.e_ceil + 1e-9 and (self.abs_gate or relax or e >= self.e_floor - 1e-9)
        return ok

    def _alloc(self, w):
        out = {a: float(w.get(a, 0.0)) for a in self.trading}
        total = sum(out.values())
        if total > 1.0:
            out = {k: v / total for k, v in out.items()}
        return TargetAllocation(out)

    # ---------- strategy ----------
    def run(self, data):
        ohlcv = data["ohlcv"]
        if len(ohlcv) < self.min_bars:
            if len(ohlcv) % 50 == 0:
                log("WAITING_FOR_HISTORY|have=%d|need=%d" % (len(ohlcv), self.min_bars))
            return TargetAllocation({})

        holdings = data.get("holdings") or {}
        cur = {a: float(holdings.get(a) or 0.0) for a in self.trading}
        invested = sum(cur.values())
        stamp = self._stamp(ohlcv[-1])[:10]

        off = self._risk_off(ohlcv) if self.use_trend else False
        off_prev = self._risk_off(ohlcv[:-1]) if self.use_trend else False

        if invested < 0.5:
            reason = "initial"
        elif self._period(ohlcv[-1]) != self._period(ohlcv[-2]):
            reason = "scheduled"
        elif self.use_trend and off is not None and off_prev is not None and off != off_prev:
            if off:
                log("%s|TREND_OFF|equity cut to %.2f of target" % (stamp, self.trend_keep))
                return self._alloc(self._derisk(cur))
            reason = "trend_on"
        else:
            return self._alloc(cur)  # between rebalances: keep current holdings, no trades

        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        df = self._frame(ohlcv[-self.bars:])
        tgt, info = self._target(df)
        if tgt is None:
            log("%s|SKIP_MISSING_DATA|held=%s|%s" % (stamp, held, reason))
            return fallback
        if not self._valid(tgt):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (stamp, reason))
            return fallback
        if off:
            tgt = self._derisk(tgt)
            if not self._valid(tgt, relax=True):
                log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s_derisk" % (stamp, reason))
                return fallback

        turn = sum(abs(tgt[a] - cur[a]) for a in self.trading) / 2.0
        log("%s|%s|eq=%.3f|neg=%d|off=%s|turn=%.3f|%s" % (
            stamp, reason, info["equity"], info["n_neg"], off, turn,
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)