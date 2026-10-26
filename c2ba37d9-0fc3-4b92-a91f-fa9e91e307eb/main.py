from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Conservative: Clenow-style dynamic tactical allocation with monthly rebalancing, 
    scaling baseline strategic sleeve weights by intra-sleeve Clenow Momentum.
    Long only, no leverage, daily bars, always invested (BIL is the cash management holding).

    Risk profile: Target equity band constrained strictly between 30% and 45% (e_floor = 0.30, e_ceil = 0.45).
    Baseline strategic targets set at 60% Equity, 35% Bonds (including GLD), and 5% Cash (BIL).
    Note: Because baseline equity (60%) exceeds the 45% ceiling, the equity band logic systematically
    rescales the equity sleeve down to 45% and the bond sleeve up to 50% during standard rebalances.

    Source: Andreas Clenow, "Technical Asset Allocation" (CMT Association, 2025) and his Investopedia series on
    dynamic asset allocation. Monthly rebalances evaluate Clenow Momentum across all holdings to scale baseline 
    weights up or down (between 0.5x and 2.0x), normalizing total risk asset exposure to 95% (5% BIL minimum floor).
    Clenow Momentum comes from "Stocks on the Move": annualized exponential regression slope (%) times R^2.

    Implementation Details & Operational Parameters:
      - Universe: 11 Equity ETFs (VT, IXN, GSLC, VIG, XLV, XLU, XLE, XLP, SPY, EFA, IJT),
                  6 Bond/Gold ETFs (GLD, AGG, IEF, BND, TIP, TLT), and 1 Cash ETF (BIL).
      - Momentum Window: 90 daily closing prices (mom_window = 90).
      - Multiplier Curve: Log-linear mapping from 0.5x (lowest rank) to 2.0x (highest rank) based on 
        percentile rank inside each sleeve.
      - Base Weights: 60% equity equal-weighted across active equity ETFs, 35% bonds equal-weighted 
        across active bond ETFs, 5% cash floor (BIL).
      - Equity Band: Bounded to [30%, 45%]. If initial risk allocation falls outside, equity and bond sleeves 
        are scaled proportionally to enforce bounds.
      - Absolute Gate (abs_gate, False by default): When enabled, assets with negative Clenow Momentum 
        are zeroed out and routed to BIL.

    Allocation Steps at Monthly Rebalance:
      1. Compute Clenow Momentum for each ETF over the trailing 90 daily closes.
      2. Calculate Intra-Sleeve Percentile Rank (r in [0, 1]) and Multiplier = 0.5 * (2.0 / 0.5) ^ r.
      3. Scale base sleeve weights by multiplier; normalize total risk exposure to 95% (BIL = 5%).
      4. Enforce Equity Band [30%, 45%]: Rescale equity and bond sleeves to nearest bound.
      5. Apply Portfolio Volatility Target scaling (if enabled).
      6. Cap single ETF exposures at 25.0% max_weight; excess routed to BIL.

    Drawdown Control & Risk Rules:
      A. Asset Volatility Cap (vol_cap, False by default): Inside each sleeve, any ETF whose 90-day 
         annualized volatility exceeds 1.0x the sleeve median is dropped (vol_cap_mult = 1.0). 
         Skipped if it would leave fewer than 3 active ETFs in the sleeve.
      B. Portfolio Volatility Target (vol_target, True by default): Realized 90-day annualized volatility 
         (vt_lookback = 90) of target weights is measured. If above 5.0% (vt_target = 0.05), all risk asset 
         weights are scaled down by (5.0% / realized_vol) with a scaling floor of 0.10 (vt_min_scale = 0.1). 
         Unallocated capital goes to BIL.
      C. Off-Schedule De-Risk Trigger (vt_trigger, True by default): Between monthly rebalances, if realized 
         90-day volatility of current holdings exceeds 1.5x target (7.5%), rebalance immediately, but ONLY if 
         the new allocation cuts risk asset exposure by at least 25 percentage points (vt_min_cut = 0.25). 
         Re-risking waits for scheduled monthly rebalances to eliminate churn.

    Guardrails & Data Safety:
      - Requires minimum 100 historical daily bars to run. Missing data forward-filled up to 5 bars.
      - Tickers with incomplete 90-day history or non-positive closes are dropped per rebalance.
      - Rebalance skips (keeping prior holdings) if fewer than 3 usable Equity ETFs or 3 usable Bond ETFs 
        remain, or if BIL pricing is unavailable.
      - Fail-Closed Constraints: Total allocation <= 1.0, non-negative weights, single ETF <= 25%, 
        equity bounded by band.
"""

    def __init__(self):
        # Universe
        self.equity = ["VT", "IXN", "GSLC", "VIG", "XLV", "XLU", "XLE", "XLP", "SPY", "EFA", "IJT"]
        self.bonds = ["GLD", "AGG", "IEF", "BND", "TIP", "TLT"]
        self.cash = "BIL"
        self.benchmark = "SPY"   # benchmark only, always 0%
        self.trading = self.equity + self.bonds + [self.cash]

        # Base (strategic) weights
        self.base_equity = 0.60
        self.base_bonds = 0.35
        self.cash_min = 0.05

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
        self.vol_cap = False
        self.vol_cap_mult = 1.0       # drop an ETF if its vol > this x the sleeve median
        self.vol_target = True
        self.vt_target = 0.05         # annualised portfolio volatility target
        self.vt_lookback = 90
        self.vt_min_scale = 0.1
        self.vt_trigger = True
        self.vt_trigger_mult = 1.5
        self.vt_min_cut = 0.25        # a de-risk trigger must cut exposure by at least this much

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