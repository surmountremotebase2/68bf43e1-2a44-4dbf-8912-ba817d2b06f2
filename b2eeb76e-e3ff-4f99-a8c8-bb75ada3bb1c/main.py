from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):
    
    """
    Clenow-style dynamic tactical allocation: static strategic base weights, scaled monthly by Clenow Momentum.
    Long only, no leverage, daily bars, always invested (BIL is the cash holding).

    Source: Andreas Clenow, "Technical Asset Allocation" (CMT Association, 2025) and his Investopedia series on
    dynamic asset allocation. Start from a fixed-weight portfolio, every month compute Clenow Momentum for every
    holding, scale each weight up or down by its momentum (at most halved or doubled), normalise back to 100%.
    Clenow Momentum comes from "Stocks on the Move": annualised exponential regression slope times R^2.

    What is from the source, and what is the implementation specification:
      Source:         monthly rebalance | same holdings and weights as the base portfolio | Clenow Momentum =
                      ((exp(slope)^252 - 1) * 100) * R^2 | weights scaled by momentum, at most halved or doubled | normalise.
      Implementation: 90-day regression window (standard window from Stocks on the Move)
                      base weights: 70% equity equal-weighted over 14 ETFs (5.0% each), 28% bonds equal-weighted over 7 ETFs (4.0% each), 2% BIL min cash reserve
                      rank-to-multiplier map: percentile rank inside each sleeve, lowest 0.5x, highest 2.0x, log-linear
                      equity band 50% to 65%: total equity share bounded within [50%, 65%] (nominal 70% base equity capped at 65% in neutral state)

    Allocation at each monthly rebalance:
      1. Clenow Momentum per ETF on the last 90 closes.
      2. Multiplier per ETF = 0.5 * (2.0 / 0.5) ^ r, r = 0..1 percentile rank inside its sleeve.
      3. Weight = base weight * multiplier, normalised so risk assets sum to 98%; BIL = 2%.
      4. Equity band: if the equity share leaves [50%, 65%], both sleeves are rescaled to the nearest bound.
      5. Optional abs_gate (off by default): an ETF with negative Clenow Momentum goes to BIL, and the equity floor is relaxed.
    Between rebalances the strategy returns the current holdings (no trades).

    Known limit: relative scaling alone gives no protection when everything falls together (2022 type markets),
    because the normalisation cancels a uniform decline. abs_gate is the only defence here.

    Guardrails (strategy fails closed and keeps holdings): sum <= 1, no negative weights, single ETF <= 25%,
    equity inside the band (unless use_band is off or abs_gate relaxes the floor).
    History: needs 100 bars. Missing data or history never raises: every skip is logged.
    """


    def __init__(self):
        # Universe
        self.equity = ["VT", "IXN", "GSLC", "VIG", "MTUM", "IMTM", "XLV", "XLU", "XLE", "XLP", "QQQ", "RSP", "EFA", "IJT"]
        self.bonds = ["GLD", "SHY", "AGG", "IEF", "BND", "TIP", "TLT"]
        self.cash = "BIL"
        self.benchmark = "SPY"   # benchmark only, always 0%
        self.trading = self.equity + self.bonds + [self.cash]

        # Base (strategic) weights
        self.base_equity = 0.70
        self.base_bonds = 0.28
        self.cash_min = 0.02

        # Clenow Momentum and weight scaling
        self.mom_window = 90
        self.m_min = 0.5
        self.m_max = 2.0

        # Risk profile
        self.use_band = True
        self.e_floor = 0.5
        self.e_ceil = 0.65
        self.max_weight = 0.25
        self.abs_gate = False

        # Monthly rebalance
        self.rebalance_months = 1

        self.min_bars = 100
        self.bars = 130

        self.base = {t: self.base_equity / len(self.equity) for t in self.equity}
        self.base.update({t: self.base_bonds / len(self.bonds) for t in self.bonds})

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

        # Optional absolute gate: negative Clenow Momentum goes to BIL
        n_neg = sum(1 for t in scored if cm[t] < 0)
        if self.abs_gate:
            for t in scored:
                if cm[t] < 0:
                    w[t] = 0.0

        tgt = {a: 0.0 for a in self.trading}
        tgt.update(w)
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity=sum(w[t] for t in self.equity), n_neg=n_neg)

    def _valid(self, w):
        e = sum(w[c] for c in self.equity)
        ok = (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
              and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9)
        if self.use_band:
            ok = ok and e <= self.e_ceil + 1e-9 and (self.abs_gate or e >= self.e_floor - 1e-9)
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

        turn = sum(abs(tgt[a] - cur[a]) for a in self.trading) / 2.0
        log("%s|%s|eq=%.3f|neg=%d|turn=%.3f|%s" % (
            stamp, reason, info["equity"], info["n_neg"], turn,
            ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)