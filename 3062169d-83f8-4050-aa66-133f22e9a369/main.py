from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.logging import log
from datetime import datetime
import math


class TradingStrategy(Strategy):
    """
    FixedIncome500 v3 — pure fixed-income dual momentum.

    - Universe: treasuries across the curve, IG credit, HY credit,
      TIPS, T-bills. No equities, no commodities.
    - Ranking: 3/6/12-month composite momentum.
    - Gate: 6-month EXCESS return vs BIL (cash) must be positive.
    - Risk scaling: gross exposure = fraction of candidates
      beating cash over 3 months (graded, not binary).
    - CPI regime: median CPI > 4% removes long duration.
    - Rebalance: first trading day of each ISO week with
      weekday >= Thursday. Deterministic per calendar date.
    """

    def __init__(self):
        self.tickers = [
            "TLT",  # Long-term treasuries (20+ yr)
            "IEF",  # Intermediate treasuries (7-10 yr)
            "LQD",  # Investment grade corporate
            "TIP",  # TIPS (inflation hedge)
            "HYG",  # High yield corporate
            "SHY",  # Short-term treasuries (1-3 yr)
            "BIL",  # Ultra-short T-Bills (cash proxy)
            "SPY",  # Benchmark only — never allocated
        ]
        self.data_list = [MedianCPI()]
        self.min_bars = 270  # 252d lookback + buffer
        self.top_n = 3
        self.last_rebalance_week = None
        self.last_allocation = None

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return self.data_list

    # ============================================================
    # HELPERS
    # ============================================================
    def get_closes(self, ohlcv, ticker):
        closes = []
        for bar in ohlcv:
            try:
                if ticker in bar and bar[ticker] and "close" in bar[ticker]:
                    p = bar[ticker]["close"]
                    if p is not None and p > 0:
                        closes.append(float(p))
            except Exception:
                pass
        return closes

    def get_bar_date(self, ohlcv):
        last = ohlcv[-1]
        for t in self.tickers:
            try:
                d = last.get(t, {}).get("date")
                if d:
                    return str(d)[:10]
            except Exception:
                pass
        return None

    def momentum(self, prices, lookback):
        if len(prices) <= lookback:
            return 0.0
        prev = prices[-1 - lookback]
        if prev is None or prev <= 0:
            return 0.0
        return (prices[-1] / prev) - 1.0

    def composite_momentum(self, prices):
        m3 = self.momentum(prices, 63)
        m6 = self.momentum(prices, 126)
        m12 = self.momentum(prices, 252)
        return 0.30 * m3 + 0.35 * m6 + 0.35 * m12

    def excess_momentum(self, prices, cash_prices, lookback):
        """Asset return minus cash (BIL) return over lookback."""
        return (
            self.momentum(prices, lookback)
            - self.momentum(cash_prices, lookback)
        )

    def realized_vol(self, prices, lookback=63):
        if len(prices) < lookback + 1:
            return None
        rets = []
        for i in range(len(prices) - lookback, len(prices)):
            if prices[i - 1] > 0:
                rets.append(prices[i] / prices[i - 1] - 1.0)
        if len(rets) < 20:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        ann_vol = math.sqrt(var) * math.sqrt(252)
        if ann_vol <= 0 or math.isnan(ann_vol) or math.isinf(ann_vol):
            return None
        return ann_vol

    def park_in_cash(self, allocation):
        parked = {t: 0.0 for t in allocation}
        parked["BIL"] = 1.0
        return TargetAllocation(parked)

    # ============================================================
    # MAIN STRATEGY
    # ============================================================
    def run(self, data):
        allocation = {t: 0.0 for t in self.tickers}
        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                return self.park_in_cash(allocation)

            # ------ Thursday-anchored weekly rebalance ------
            date_str = self.get_bar_date(ohlcv)
            week_key = None
            if date_str is not None:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                iso_year, iso_week, iso_weekday = d.isocalendar()
                week_key = (iso_year, iso_week)
                do_rebalance = (
                    iso_weekday >= 4
                    and week_key != self.last_rebalance_week
                )
            else:
                do_rebalance = True  # fail open

            if not do_rebalance:
                if self.last_allocation is not None:
                    return TargetAllocation(self.last_allocation)
                return self.park_in_cash(allocation)

            closes = {t: self.get_closes(ohlcv, t) for t in self.tickers}
            for t in self.tickers:
                if len(closes[t]) < self.min_bars:
                    return self.park_in_cash(allocation)

            if week_key is not None:
                self.last_rebalance_week = week_key

            cash = closes["BIL"]

            # ------ CPI regime: >4% removes long duration ------
            median_cpi_data = data.get(("median_cpi",))
            latest_cpi = 0.0
            if median_cpi_data and len(median_cpi_data) > 0:
                latest_cpi = median_cpi_data[-1].get("value", 0.0)
            inflation_on = latest_cpi > 4.0

            if inflation_on:
                candidates = ["TIP", "SHY", "HYG", "LQD"]
                safe_haven = "BIL"
            else:
                candidates = ["TLT", "IEF", "LQD", "HYG", "TIP"]
                safe_haven = "SHY"

            # ------ Dual momentum selection ------
            # Rank by 3/6/12m composite; hold only those whose
            # 6-month return BEATS CASH.
            scores = {
                t: self.composite_momentum(closes[t]) for t in candidates
            }
            ranked = sorted(
                scores.keys(), key=lambda t: scores[t], reverse=True
            )
            eligible = [
                t for t in ranked
                if self.excess_momentum(closes[t], cash, 126) > 0
            ]
            hold = eligible[: self.top_n]

            # ------ Graded risk scaling (breadth) ------
            # Gross exposure = fraction of candidates beating
            # cash over 3 months. Broad selloff -> gross falls
            # proportionally; no single-ticker binary flips.
            beating = sum(
                1 for t in candidates
                if self.excess_momentum(closes[t], cash, 63) > 0
            )
            gross = beating / len(candidates)

            # ------ Weights ------
            if hold and gross > 0:
                vols = {}
                for t in hold:
                    v = self.realized_vol(closes[t], 63)
                    vols[t] = v if (v and v > 0) else 0.10
                inv = {t: 1.0 / vols[t] for t in hold}
                inv_total = sum(inv.values())
                weights = {
                    t: (inv[t] / inv_total) * gross for t in hold
                }
                defensive = 1.0 - gross
            else:
                weights = {}
                defensive = 1.0

            # Defensive sleeve: split safe haven / cash
            if defensive > 0:
                if safe_haven == "BIL":
                    weights["BIL"] = weights.get("BIL", 0) + defensive
                else:
                    weights[safe_haven] = (
                        weights.get(safe_haven, 0) + defensive * 0.5
                    )
                    weights["BIL"] = (
                        weights.get("BIL", 0) + defensive * 0.5
                    )

            # ------ Apply & normalize ------
            for t, w in weights.items():
                if t in allocation:
                    allocation[t] = round(w, 4)
            total = sum(allocation.values())
            if total > 1.0:
                allocation = {k: v / total for k, v in allocation.items()}

            self.last_allocation = dict(allocation)
            held = [
                (t, round(w, 3))
                for t, w in allocation.items()
                if w > 0
            ]
            log(
                f"Rebalance {date_str} | CPI {latest_cpi:.1f} "
                f"| gross {gross:.2f} | {held}"
            )
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Error: {e}")
            if self.last_allocation is not None:
                return TargetAllocation(self.last_allocation)
            return self.park_in_cash(allocation)