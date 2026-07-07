from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.logging import log
from datetime import datetime
import math


class TradingStrategy(Strategy):
    """
    FixedIncome500 v3.1 — pure fixed-income dual momentum, STATELESS.

    Decision logic is a pure function of (calendar, price history):
    every bar, we locate the most recent Thursday-anchored decision
    bar (first bar of its ISO week with weekday >= Thu), slice the
    price history up to that bar, and compute the allocation from
    the slice. Identical output whether or not the platform
    persists instance state, replays bars, or re-instantiates.
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
        self.min_bars = 140          # 126d momentum + buffer
        self.top_n = 3
        self._cache = {}             # optional speedup only —
                                     # correctness never depends on it

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
    # DATE / SLICING HELPERS
    # ============================================================
    def bar_date(self, ohlcv, i):
        """Date string 'YYYY-MM-DD' of bar i, or None."""
        bar = ohlcv[i]
        for t in self.tickers:
            try:
                v = bar.get(t)
                if v and v.get("date"):
                    return str(v["date"])[:10]
            except Exception:
                pass
        return None

    def iso_tuple(self, date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        y, w, wd = d.isocalendar()
        return (y, w, wd)

    def find_decision_index(self, ohlcv):
        """
        Index of the most recent decision bar: the FIRST bar of its
        ISO week whose weekday >= 4 (Thursday; Friday if Thursday
        was a holiday). Scans back at most 15 bars — always enough
        to cover the current and previous week.
        Returns (index, date_str) or (None, None).
        """
        n = len(ohlcv)
        lo = max(1, n - 15)
        for i in range(n - 1, lo - 1, -1):
            ds = self.bar_date(ohlcv, i)
            ds_prev = self.bar_date(ohlcv, i - 1)
            if ds is None or ds_prev is None:
                continue
            try:
                y, w, wd = self.iso_tuple(ds)
                py, pw, pwd = self.iso_tuple(ds_prev)
            except Exception:
                continue
            if wd >= 4 and ((py, pw) != (y, w) or pwd < 4):
                return i, ds
        return None, None

    # ============================================================
    # SIGNAL HELPERS (operate on plain close lists)
    # ============================================================
    def get_closes(self, ohlcv_slice, ticker):
        closes = []
        for bar in ohlcv_slice:
            try:
                if ticker in bar and bar[ticker] and "close" in bar[ticker]:
                    p = bar[ticker]["close"]
                    if p is not None and p > 0:
                        closes.append(float(p))
            except Exception:
                pass
        return closes

    def momentum(self, prices, lookback):
        """Return over lookback, or None if history insufficient."""
        if len(prices) <= lookback:
            return None
        prev = prices[-1 - lookback]
        if prev is None or prev <= 0:
            return None
        return (prices[-1] / prev) - 1.0

    def composite_momentum(self, prices):
        """3/6/12m composite; renormalizes over available horizons."""
        parts = [
            (0.30, self.momentum(prices, 63)),
            (0.35, self.momentum(prices, 126)),
            (0.35, self.momentum(prices, 252)),
        ]
        avail = [(w, m) for w, m in parts if m is not None]
        if not avail:
            return 0.0
        wsum = sum(w for w, _ in avail)
        return sum(w * m for w, m in avail) / wsum

    def excess_momentum(self, prices, cash_prices, lookback):
        a = self.momentum(prices, lookback)
        c = self.momentum(cash_prices, lookback)
        if a is None or c is None:
            return None
        return a - c

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
        v = math.sqrt(var) * math.sqrt(252)
        if v <= 0 or math.isnan(v) or math.isinf(v):
            return None
        return v

    def park_in_cash(self):
        parked = {t: 0.0 for t in self.tickers}
        parked["BIL"] = 1.0
        return TargetAllocation(parked)

    # ============================================================
    # PURE DECISION FUNCTION
    # ============================================================
    def compute_allocation(self, ohlcv_slice, cpi_value, date_str):
        """Allocation dict from a price slice. No side effects."""
        closes = {
            t: self.get_closes(ohlcv_slice, t) for t in self.tickers
        }
        short = [
            t for t in self.tickers
            if len(closes[t]) < self.min_bars
        ]
        if short:
            log(f"{date_str}: park (insufficient bars: {short})")
            return None  # caller parks in cash

        cash = closes["BIL"]
        inflation_on = cpi_value > 4.0

        if inflation_on:
            candidates = ["TIP", "SHY", "HYG", "LQD"]
            safe_haven = "BIL"
        else:
            candidates = ["TLT", "IEF", "LQD", "HYG", "TIP"]
            safe_haven = "SHY"

        # Dual momentum: rank by composite, gate on 6m excess vs cash
        scores = {
            t: self.composite_momentum(closes[t]) for t in candidates
        }
        ranked = sorted(
            scores.keys(), key=lambda t: scores[t], reverse=True
        )
        eligible = []
        for t in ranked:
            ex = self.excess_momentum(closes[t], cash, 126)
            if ex is not None and ex > 0:
                eligible.append(t)
        hold = eligible[: self.top_n]

        # Graded risk scaling: breadth of 3m excess momentum
        beating = 0
        for t in candidates:
            ex = self.excess_momentum(closes[t], cash, 63)
            if ex is not None and ex > 0:
                beating += 1
        gross = beating / len(candidates)

        weights = {}
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
        defensive = 1.0 - sum(weights.values())

        if defensive > 1e-9:
            if safe_haven == "BIL":
                weights["BIL"] = weights.get("BIL", 0) + defensive
            else:
                weights[safe_haven] = (
                    weights.get(safe_haven, 0) + defensive * 0.5
                )
                weights["BIL"] = (
                    weights.get("BIL", 0) + defensive * 0.5
                )

        allocation = {t: 0.0 for t in self.tickers}
        for t, w in weights.items():
            if t in allocation:
                allocation[t] = round(w, 4)
        total = sum(allocation.values())
        if total > 1.0:
            allocation = {k: v / total for k, v in allocation.items()}

        held = [(t, round(w, 3)) for t, w in allocation.items() if w > 0]
        log(
            f"Decision {date_str} | CPI {cpi_value:.1f} | "
            f"eligible {eligible} | gross {gross:.2f} | {held}"
        )
        return allocation

    # ============================================================
    # MAIN
    # ============================================================
    def run(self, data):
        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                log(
                    f"park: warmup {len(ohlcv)}/{self.min_bars} bars"
                )
                return self.park_in_cash()

            idx, decision_date = self.find_decision_index(ohlcv)
            if idx is None:
                log("park: no decision bar found (missing dates)")
                return self.park_in_cash()

            # Cache is a speedup only; a cold cache just recomputes.
            if decision_date in self._cache:
                return TargetAllocation(self._cache[decision_date])

            cpi_value = 0.0
            cpi_data = data.get(("median_cpi",))
            if cpi_data and len(cpi_data) > 0:
                cpi_value = cpi_data[-1].get("value", 0.0)

            allocation = self.compute_allocation(
                ohlcv[: idx + 1], cpi_value, decision_date
            )
            if allocation is None:
                return self.park_in_cash()

            self._cache[decision_date] = allocation
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Error: {e}")
            return self.park_in_cash()