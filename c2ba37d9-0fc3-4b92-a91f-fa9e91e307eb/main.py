from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):

    """
    Conservative Clenow-style dynamic tactical allocation with a trend circuit breaker.
    Long only, no leverage, daily bars, always invested (BIL is the cash holding).

    Risk profile: Conservative (capital preservation first, income second).
      Base mix: 30% equity, 65% defensive (bonds + 6% gold), 5% BIL.
      Equity band: 20% to 35%. Momentum multiplier 0.75x to 1.33x.
      abs_gate ON: an ETF with negative Clenow Momentum goes to BIL (this is what limits 2022 type losses).
      Trend circuit breaker: when VT closes below its 200-day average, equity is cut to 25% of its
      target weight and the difference goes to BIL. Checked daily, acts only on the crossing day, and
      is exempt from the equity floor. Back above the average, a fresh target is computed.

    Source: Andreas Clenow, "Technical Asset Allocation" (CMT Association, 2025).
    Clenow Momentum = ((exp(slope)^252 - 1) * 100) * R^2 on a 90-day log-price regression.

    Allocation at each monthly rebalance:
      1. Clenow Momentum per ETF on the last 90 closes.
      2. Multiplier per ETF = m_min * (m_max / m_min) ^ r, r = 0..1 percentile rank inside its sleeve.
      3. Weight = base weight * multiplier, normalised so risk assets sum to 95%; BIL = 5%.
      4. Equity band: if the equity share leaves [20%, 35%], both sleeves are rescaled to the nearest bound.
      5. abs_gate: negative Clenow Momentum goes to BIL.
      6. If the trend breaker is active, equity is cut (see above).
    Between rebalances the strategy returns the current holdings, except on a trend crossing day.

    Guardrails (fail closed, keep holdings): sum <= 1, no negative weights, single ETF <= 25%,
    equity inside the band (floor relaxed by abs_gate and by the trend breaker).
    History: needs 210 bars. Missing data never raises: every skip is logged.
    """

    def __init__(self):
        # Universe
        self.equity = ["VT", "VIG", "GSLC", "RSP", "EFA", "XLV", "XLU", "XLP"]
        self.bonds = ["SHY", "AGG", "BND", "IEF", "TIP", "TLT", "GLD"]   # defensive sleeve, GLD is the 6% diversifier
        self.cash = "BIL"
        self.benchmark = "SPY"   # benchmark only, always 0%
        self.trading = self.equity + self.bonds + [self.cash]

        # Base (strategic) weights: 30 / 65 / 5
        self.base_equity = 0.30
        self.base_bonds = 0.65
        self.cash_min = 0.05

        # Clenow Momentum and weight scaling
        self.mom_window = 90
        self.m_min = 0.75
        self.m_max = 1.33

        # Risk profile
        self.use_band = True
        self.e_floor = 0.20
        self.e_ceil = 0.35
        self.max_weight = 0.25
        self.abs_gate = True

        # Trend circuit breaker
        self.use_trend = True
        self.trend_ticker = "VT"
        self.trend_window = 200
        self.trend_keep = 0.25   # share of the equity target kept while risk-off

        # Monthly rebalance
        self.rebalance_months = 1

        self.min_bars = 210
        self.bars = 260

        self.base = {t: self.base_equity / len(self.equity) for t in self.equity}
        self.base.update({"SHY": 0.12, "AGG": 0.14, "BND": 0.14, "IEF": 0.10,
                          "TIP": 0.06, "TLT": 0.03, "GLD": 0.06})  # sums to 0.65

    @property
    def assets(self):
        return self.trading + [self.benchmark]

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
        """True if the trend ticker closes below its trend_window average at the last bar. None if data is missing."""
        n = self.trend_window
        if len(rows) < n:
            return None
        c = [bar[self.trend_ticker]["close"] if self.trend_ticker in bar else float("nan") for bar in rows[-n:]]
        if any(x != x for x in c):
            return None
        return c[-1] < sum(c) / n

    def _derisk(self, w):
        """Keep trend_keep of each equity weight, move the rest to BIL."""
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

        # Momentum multiplier: percentile rank inside the sleeve, lowest m_min ... highest m_max
        mult = {}
        for group in (self.equity, self.bonds):
            rk = pd.Series({t: cm[t] for t in group}).rank(method="average")
            for t in group:
                r = (rk[t] - 1.0) / (len(group) - 1.0)
                mult[t] = self.m_min * (self.m_max / self.m_min) ** r

        risky = 1.0 - self.cash_min
        raw = {t: self.base[t] * mult[t] for t in scored}
        tot = sum(raw.values())
        w = {t: raw[t] / tot * risky for t in scored}

        # Equity band: rescale both sleeves to the nearest bound
        if self.use_band:
            e = sum(w[t] for t in self.equity)
            e2 = min(max(e, self.e_floor), self.e_ceil)
            if abs(e2 - e) > 1e-12:
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
        out[self.benchmark] = 0.0
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