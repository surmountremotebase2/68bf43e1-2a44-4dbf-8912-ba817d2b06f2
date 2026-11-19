from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Conservative, long-only Clenow-style tactical allocation.

    - Daily bars; monthly rebalance; BIL is the cash holding.
    - Risk assets target 95%; BIL holds the remaining 5%.
    - Equity exposure is constrained to 20%-35%.
    - ETFs with negative Clenow Momentum are moved to BIL.
    - SPY below its 200-day average cuts equity exposure to 10% of target.
    """

    def __init__(self):
        # Investable universe
        self.equity = [
            "VT", "IXN", "GSLC", "VIG", "MTUM", "IMTM", "XLV", "XLU",
            "XLE", "XLP", "QQQ", "RSP", "EFA", "IJT"
        ]
        self.bonds = ["GLD", "SHY", "AGG", "IEF", "BND", "TIP", "TLT"]
        self.cash = "BIL"
        self.trading = self.equity + self.bonds + [self.cash]

        # Strategic allocation: 40% equity, 55% bonds, 5% cash
        self.base_equity = 0.40
        self.base_bonds = 0.55
        self.cash_min = 0.05

        # Clenow Momentum settings
        self.mom_window = 90
        self.m_min = 0.75
        self.m_max = 1.20

        # Risk constraints
        self.use_band = True
        self.e_floor = 0.20
        self.e_ceil = 0.35
        self.max_weight = 0.25
        self.abs_gate = True

        # Trend circuit breaker
        self.use_trend = True
        self.trend_ticker = "SPY"
        self.trend_window = 200
        self.trend_keep = 0.10  # Keep 10% of equity target during risk-off

        # Rebalance monthly
        self.rebalance_months = 1

        # Require enough history for momentum and trend calculations
        self.min_bars = 210
        self.bars = 260

        # Equal-weight equity base; explicit bond base weights
        self.base = {t: self.base_equity / len(self.equity) for t in self.equity}
        self.base.update({
            "SHY": 0.13, "AGG": 0.14, "BND": 0.10, "IEF": 0.03,
            "TIP": 0.04, "TLT": 0.03, "GLD": 0.03
        })

    @property
    def assets(self):
        return self.trading + [self.trend_ticker]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # Price data only

    # ---------- Helpers ----------

    @staticmethod
    def _stamp(bar):
        """Return the date string from the first value in a bar."""
        for value in bar.values():
            return str(value["date"])
        return ""

    def _period(self, bar):
        """Return the rebalance period for a bar."""
        stamp = self._stamp(bar)
        try:
            return (int(stamp[:4]) * 12 + int(stamp[5:7]) - 1) // self.rebalance_months
        except ValueError:
            return -1

    def _frame(self, rows):
        """Build a close-price DataFrame from OHLCV rows."""
        return pd.DataFrame({
            t: [bar[t]["close"] if t in bar else float("nan") for bar in rows]
            for t in self.trading
        })

    @staticmethod
    def _clenow(closes):
        """Clenow Momentum: annualised regression slope times R-squared."""
        y = np.log(np.asarray(closes, dtype=float))
        x = np.arange(len(y), dtype=float)

        slope, intercept = np.polyfit(x, y, 1)
        ss_tot = float(((y - y.mean()) ** 2).sum())

        r2 = 0.0
        if ss_tot > 0:
            r2 = 1.0 - float(((y - (slope * x + intercept)) ** 2).sum()) / ss_tot

        return (math.exp(slope) ** 252 - 1.0) * 100.0 * r2

    def _risk_off(self, rows):
        """Return True when SPY closes below its 200-day average."""
        n = self.trend_window
        if len(rows) < n:
            return None

        closes = [
            bar[self.trend_ticker]["close"] if self.trend_ticker in bar else float("nan")
            for bar in rows[-n:]
        ]

        if any(x != x for x in closes):
            return None

        return closes[-1] < sum(closes) / n

    def _derisk(self, weights):
        """Cut equity exposure to trend_keep; move the reduction to BIL."""
        out = dict(weights)

        cut = sum(out[t] for t in self.equity) * (1.0 - self.trend_keep)

        for t in self.equity:
            out[t] *= self.trend_keep

        out[self.cash] += cut
        return out

    def _target(self, df):
        """Calculate target weights from the latest available data."""
        scored = self.equity + self.bonds
        n = self.mom_window

        if len(df) < n:
            return None, {}

        window = df.iloc[-n:]

        # Skip if required prices are missing or non-positive
        if window[scored].isna().any().any() or pd.isna(df[self.cash].iloc[-1]):
            return None, {}

        if (window[scored] <= 0).any().any():
            return None, {}

        # Calculate Clenow Momentum
        momentum = {t: self._clenow(window[t].values) for t in scored}

        # Scale each sleeve by momentum percentile rank
        multiplier = {}
        for group in (self.equity, self.bonds):
            ranks = pd.Series({t: momentum[t] for t in group}).rank(method="average")

            for t in group:
                rank = (ranks[t] - 1.0) / (len(group) - 1.0)
                multiplier[t] = self.m_min * (self.m_max / self.m_min) ** rank

        # Allocate 95% to risk assets; BIL retains 5%
        risky = 1.0 - self.cash_min
        raw = {t: self.base[t] * multiplier[t] for t in scored}
        total = sum(raw.values())

        weights = {t: raw[t] / total * risky for t in scored}

        # Enforce the equity band by rescaling both sleeves
        if self.use_band:
            equity_weight = sum(weights[t] for t in self.equity)
            target_equity = min(max(equity_weight, self.e_floor), self.e_ceil)

            if abs(target_equity - equity_weight) > 1e-12:
                for t in self.equity:
                    weights[t] *= target_equity / equity_weight

                for t in self.bonds:
                    weights[t] *= (risky - target_equity) / (risky - equity_weight)

        # Move ETFs with negative momentum to BIL
        negative_count = sum(1 for t in scored if momentum[t] < 0)

        if self.abs_gate:
            for t in scored:
                if momentum[t] < 0:
                    weights[t] = 0.0

        # Build final allocation
        target = {a: 0.0 for a in self.trading}
        target.update(weights)
        target[self.cash] = max(
            0.0,
            1.0 - sum(v for k, v in target.items() if k != self.cash) - 1e-9
        )

        info = {
            "equity": sum(weights[t] for t in self.equity),
            "n_neg": negative_count
        }

        return target, info

    def _valid(self, weights, relax=False):
        """Validate allocation guardrails; optionally relax the equity floor."""
        equity = sum(weights[c] for c in self.equity)

        ok = (
            sum(weights.values()) <= 1.0 + 1e-9
            and min(weights.values()) >= -1e-12
            and max(v for k, v in weights.items() if k != self.cash) <= self.max_weight + 1e-9
        )

        if self.use_band:
            ok = ok and equity <= self.e_ceil + 1e-9
            ok = ok and (self.abs_gate or relax or equity >= self.e_floor - 1e-9)

        return ok

    def _alloc(self, weights):
        """Return a normalised TargetAllocation."""
        allocation = {a: float(weights.get(a, 0.0)) for a in self.trading}
        total = sum(allocation.values())

        if total > 1.0:
            allocation = {k: v / total for k, v in allocation.items()}

        return TargetAllocation(allocation)

    # ---------- Strategy ----------

    def run(self, data):
        ohlcv = data["ohlcv"]

        # Wait until enough history is available
        if len(ohlcv) < self.min_bars:
            if len(ohlcv) % 50 == 0:
                log("WAITING_FOR_HISTORY|have=%d|need=%d" % (len(ohlcv), self.min_bars))
            return TargetAllocation({})

        holdings = data.get("holdings") or {}
        current = {a: float(holdings.get(a) or 0.0) for a in self.trading}
        invested = sum(current.values())
        stamp = self._stamp(ohlcv[-1])[:10]

        # Detect trend-state changes
        risk_off = self._risk_off(ohlcv) if self.use_trend else False
        risk_off_prev = self._risk_off(ohlcv[:-1]) if self.use_trend else False

        # Rebalance on initial investment, month change, or trend crossing
        if invested < 0.5:
            reason = "initial"
        elif self._period(ohlcv[-1]) != self._period(ohlcv[-2]):
            reason = "scheduled"
        elif self.use_trend and risk_off is not None and risk_off_prev is not None and risk_off != risk_off_prev:
            if risk_off:
                log("%s|TREND_OFF|equity cut to %.2f of target" % (stamp, self.trend_keep))
                return self._alloc(self._derisk(current))
            reason = "trend_on"
        else:
            return self._alloc(current)  # Hold between scheduled rebalances

        held = invested >= 0.5
        fallback = self._alloc(current) if held else TargetAllocation({})

        # Calculate the new target allocation
        df = self._frame(ohlcv[-self.bars:])
        target, info = self._target(df)

        # Keep prior holdings if data is insufficient
        if target is None:
            log("%s|SKIP_MISSING_DATA|held=%s|%s" % (stamp, held, reason))
            return fallback

        # Keep prior holdings if guardrails fail
        if not self._valid(target):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (stamp, reason))
            return fallback

        # Apply trend-based de-risking
        if risk_off:
            target = self._derisk(target)

            if not self._valid(target, relax=True):
                log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s_derisk" % (stamp, reason))
                return fallback

        # Log turnover and allocation details
        turnover = sum(abs(target[a] - current[a]) for a in self.trading) / 2.0


        return self._alloc(target)