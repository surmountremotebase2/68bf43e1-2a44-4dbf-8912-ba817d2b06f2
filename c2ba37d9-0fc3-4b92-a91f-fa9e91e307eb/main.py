from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Conservative: Clenow-style dynamic tactical allocation, static strategic weights scaled monthly by Clenow Momentum.
    Long only, no leverage, daily bars, always invested (BIL is the cash holding).

    Risk profile: anchor 40% equity, band 30% to 45% (reference: Vanguard LifeStrategy Conservative Growth, 40/60).
    The rest is bonds (and GLD, which sits in the bond sleeve) and BIL (2%).

    Source: Andreas Clenow, "Technical Asset Allocation" (CMT Association, 2025) and his Investopedia series on
    dynamic asset allocation. Start from a fixed-weight portfolio, every month compute Clenow Momentum for every
    holding, scale each weight up or down by its momentum (at most halved or doubled), normalise back to 100%.
    Clenow Momentum comes from "Stocks on the Move": annualised exponential regression slope times R^2.

    What is from the source, and what is my assumption (the slides give no code):
      Source:     monthly rebalance | same holdings and weights as the base portfolio | Clenow Momentum =
                  ((exp(slope)^252 - 1) * 100) * R^2 | weights scaled by momentum, at most halved or doubled | normalise.
      Assumption: 90-day regression window (the value used in Stocks on the Move)
                  base weights: 40% equity equal-weighted over 14 ETFs, 58% bonds equal-weighted over 7, 2% BIL
                  rank-to-multiplier map: percentile rank inside each sleeve, lowest 0.5x, highest 2.0x, log-linear
                  equity band 30% to 45% (use_band=False = pure Clenow, equity floats)

    Allocation at each monthly rebalance:
      1. Clenow Momentum per ETF on the last 90 closes.
      2. Multiplier per ETF = 0.5 * (2.0 / 0.5) ^ r, r = 0..1 percentile rank inside its sleeve.
      3. Weight = base weight * multiplier, normalised so risk assets sum to 98%; BIL = 2%.
      4. Equity band: if the equity share leaves [30%, 45%], both sleeves are rescaled to the nearest bound.
      5. Optional abs_gate (off by default): an ETF with negative Clenow Momentum goes to BIL, and the equity floor is relaxed.
    Between rebalances the strategy returns the current holdings (no trades).

    Drawdown control (both on by default, each can be switched off):
      A. Asset volatility cap (vol_cap): inside each sleeve, an ETF whose 90-day annualised volatility is above 2x
         the sleeve median is dropped for that rebalance (named as vcap=... in the log). Skipped if it would leave
         fewer than 3 ETFs in the sleeve.
      B. Portfolio volatility target (vol_target): the realised 63-day volatility of the target weights is
         measured; if it is above 6%, all risk weights are scaled by 6% / vol (floor 0.2), the rest goes to BIL.
         Long only, never levered. This lets equity fall below the band floor in turbulent markets; the ceiling stays.
      C. De-risk trigger (vt_trigger): between monthly rebalances, if the realised volatility of the current holdings
         exceeds 1.5x the target, rebalance now, but only if that cuts risk exposure by at least 5 points.
         Re-risking waits for the next monthly rebalance, so volatility flicker does not create churn.

    Known limit: relative scaling alone gives no protection when everything falls together (2022 type markets),
    because the normalisation cancels a uniform decline. abs_gate is the only defence here.

    Guardrails (strategy fails closed and keeps holdings): sum <= 1, no negative weights, single ETF <= 25%,
    equity inside the band (unless use_band is off or abs_gate relaxes the floor).
    History: needs 100 bars. Missing data or history never raises: every skip is logged.
    Data handling: short gaps (missing prints) are forward-filled up to 5 bars. A ticker that still has missing or
    non-positive closes in the 90-day window is dropped for that rebalance (named in the log as dropped=...), and the
    base weights are spread over the remaining ETFs of its sleeve. The rebalance is skipped only if fewer than 3
    equity ETFs or fewer than 3 bond ETFs remain, or BIL has no price.
    """

    def __init__(self):
        # Universe
        self.equity = ["VT", "IXN", "GSLC", "VIG", "MTUM", "IMTM", "XLV", "XLU", "XLE", "XLP", "QQQ", "RSP", "EFA", "IJT"]
        self.bonds = ["GLD", "SHY", "AGG", "IEF", "BND", "TIP", "TLT"]
        self.cash = "BIL"
        self.benchmark = "SPY"   # benchmark only, always 0%
        self.trading = self.equity + self.bonds + [self.cash]

        # Base (strategic) weights
        self.base_equity = 0.40
        self.base_bonds = 0.58
        self.cash_min = 0.02

        # Clenow Momentum and weight scaling
        self.mom_window = 90
        self.m_min = 0.5
        self.m_max = 2.0

        # Risk profile
        self.use_band = True
        self.e_floor = 0.30
        self.e_ceil = 0.45
        self.max_weight = 0.25
        self.abs_gate = False

        # Drawdown control
        self.vol_cap = True
        self.vol_cap_mult = 2.0       # drop an ETF if its vol > this x the sleeve median
        self.vol_target = True
        self.vt_target = 0.06         # annualised portfolio volatility target
        self.vt_lookback = 63
        self.vt_min_scale = 0.2
        self.vt_trigger = True
        self.vt_trigger_mult = 1.5
        self.vt_min_cut = 0.05        # a de-risk trigger must cut exposure by at least this much

        # Monthly rebalance
        self.rebalance_months = 1

        self.min_bars = 100
        self.bars = 130
        self.ffill_limit = 5      # forward-fill gaps up to this many bars
        self.min_names = 3        # minimum usable ETFs per sleeve

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

    def _port_vol(self, df, w):
        """Annualised realised volatility of weights w (cash excluded) over the last vt_lookback returns."""
        names = [t for t in w if t != self.cash and w[t] > 0 and t in df.columns]
        if not names:
            return 0.0
        rets = df[names].pct_change().iloc[-self.vt_lookback:].fillna(0.0)
        r = sum(rets[t] * w[t] for t in names)
        return float(r.std() * math.sqrt(252))

    @staticmethod
    def _clenow(closes):
        """Annualised exponential regression slope (%) times R^2, on the given closes."""
        y = np.log(np.asarray(closes, dtype=float))
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - float(((y - (slope * x + intercept)) ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
        return (math.exp(slope) ** 252 - 1.0) * 100.0 * r2

    def _target(self, df):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        df = df.ffill(limit=self.ffill_limit)
        scored = self.equity + self.bonds
        n = self.mom_window
        if len(df) < n:
            return None, dict(dropped=[], n_eq=0, n_bd=0, why="HISTORY")
        if pd.isna(df[self.cash].iloc[-1]):
            return None, dict(dropped=[self.cash], n_eq=0, n_bd=0, why="BIL_NO_PRICE")
        win = df.iloc[-n:]
        good = [t for t in scored if win[t].notna().all() and (win[t] > 0).all()]
        dropped = [t for t in scored if t not in good]
        eq_u = [t for t in self.equity if t in good]
        bd_u = [t for t in self.bonds if t in good]
        if len(eq_u) < self.min_names or len(bd_u) < self.min_names:
            return None, dict(dropped=dropped, n_eq=len(eq_u), n_bd=len(bd_u), why="TOO_FEW_ETFS")
        rets = df.pct_change()
        dropped_vol = []
        if self.vol_cap:
            for group in (eq_u, bd_u):
                vol = {t: float(rets[t].iloc[-(n - 1):].std() * math.sqrt(252)) for t in group}
                med = float(np.median(list(vol.values())))
                keep = [t for t in group if vol[t] <= self.vol_cap_mult * med]
                if len(keep) >= self.min_names and len(keep) < len(group):
                    dropped_vol += [t for t in group if t not in keep]
                    group[:] = keep
        scored = eq_u + bd_u
        base = {t: self.base_equity / len(eq_u) for t in eq_u}
        base.update({t: self.base_bonds / len(bd_u) for t in bd_u})

        cm = {t: self._clenow(win[t].values) for t in scored}

        # Momentum multiplier: percentile rank inside the sleeve, lowest m_min ... highest m_max
        mult = {}
        for group in (eq_u, bd_u):
            rk = pd.Series({t: cm[t] for t in group}).rank(method="average")
            for t in group:
                r = (rk[t] - 1.0) / (len(group) - 1.0)
                mult[t] = self.m_min * (self.m_max / self.m_min) ** r

        risky = 1.0 - self.cash_min
        raw = {t: base[t] * mult[t] for t in scored}
        tot = sum(raw.values())
        w = {t: raw[t] / tot * risky for t in scored}

        # Equity band: rescale both sleeves to the nearest bound
        if self.use_band:
            e = sum(w[t] for t in eq_u)
            e2 = min(max(e, self.e_floor), self.e_ceil)
            if abs(e2 - e) > 1e-12:
                for t in eq_u:
                    w[t] *= e2 / e
                for t in bd_u:
                    w[t] *= (risky - e2) / (risky - e)

        # Optional absolute gate: negative Clenow Momentum goes to BIL
        n_neg = sum(1 for t in scored if cm[t] < 0)
        if self.abs_gate:
            for t in scored:
                if cm[t] < 0:
                    w[t] = 0.0

        # Portfolio volatility target: scale risk weights down, never up
        scale, pv = 1.0, float("nan")
        if self.vol_target:
            pv = self._port_vol(df, w)
            if pv > 0:
                scale = min(1.0, max(self.vt_min_scale, self.vt_target / pv))
            for t in scored:
                w[t] *= scale

        # Single-ETF cap: the excess stays unallocated and goes to BIL
        for t in scored:
            w[t] = min(w[t], self.max_weight)

        tgt = {a: 0.0 for a in self.trading}
        tgt.update(w)
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity=sum(w[t] for t in eq_u), n_neg=n_neg, dropped=dropped, n_eq=len(eq_u), n_bd=len(bd_u),
                         vcap=dropped_vol, scale=scale, vol=pv)

    def _valid(self, w):
        e = sum(w[c] for c in self.equity)
        ok = (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
              and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9)
        if self.use_band:
            ok = ok and e <= self.e_ceil + 1e-9 and (self.abs_gate or self.vol_target or e >= self.e_floor - 1e-9)
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

        if invested < 0.5:
            reason = "initial"
        elif self._period(ohlcv[-1]) != self._period(ohlcv[-2]):
            reason = "scheduled"
        elif self.vol_target and self.vt_trigger:
            df0 = self._frame(ohlcv[-self.bars:]).ffill(limit=self.ffill_limit)
            if self._port_vol(df0, cur) > self.vt_trigger_mult * self.vt_target:
                reason = "vol_breach"
            else:
                return self._alloc(cur)
        else:
            return self._alloc(cur)  # between rebalances: keep current holdings, no trades

        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        df = self._frame(ohlcv[-self.bars:])
        tgt, info = self._target(df)
        if tgt is None:
            log("%s|SKIP_%s|held=%s|%s|eq_ok=%d|bd_ok=%d|dropped=%s" % (
                stamp, info["why"], held, reason, info["n_eq"], info["n_bd"], ",".join(info["dropped"])))
            return fallback
        if reason == "vol_breach":
            risk_tgt = sum(v for k, v in tgt.items() if k != self.cash)
            risk_cur = sum(cur[a] for a in self.trading if a != self.cash)
            if risk_tgt > risk_cur - self.vt_min_cut:
                return self._alloc(cur)  # de-risk only: ignore triggers that would not cut exposure
        if not self._valid(tgt):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (stamp, reason))
            return fallback

        turn = sum(abs(tgt[a] - cur[a]) for a in self.trading) / 2.0
        log("%s|%s|eq=%.3f|vol=%.3f|scale=%.2f|neg=%d|turn=%.3f|dropped=%s|vcap=%s|%s" % (
            stamp, reason, info["equity"], info["vol"], info["scale"], info["n_neg"], turn,
            ",".join(info["dropped"]) or "-", ",".join(info["vcap"]) or "-",
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)