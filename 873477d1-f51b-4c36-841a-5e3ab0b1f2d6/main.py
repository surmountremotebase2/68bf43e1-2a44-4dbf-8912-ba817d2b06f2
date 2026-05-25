from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.data import MedianCPI
from surmount.logging import log
import math


class TradingStrategy(Strategy):

    def __init__(self):
        self.tickers = [
            "TLT",  # Long-term treasuries (20+ yr)
            "IEF",  # Intermediate treasuries (7-10 yr)
            "LQD",  # Investment grade corporate
            "TIP",  # TIPS (inflation hedge)
            "HYG",  # High yield corporate
            "SHY",  # Short-term treasuries (1-3 yr)
            "BIL",  # Ultra-short T-Bills (1-3 mo)
            "GLD",  # Gold (tail-risk hedge)
        ]
        self.data_list = [MedianCPI()]
        self.min_bars = 140
        self.warmup = 1
        self.rebalance_freq = 5
        self.bar_count = 0
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
                if (
                    ticker in bar
                    and bar[ticker]
                    and "close" in bar[ticker]
                ):
                    p = bar[ticker]["close"]
                    if p is not None and p > 0:
                        closes.append(float(p))
            except Exception:
                pass
        return closes

    def momentum(self, prices, lookback):
        if len(prices) <= lookback:
            return 0.0
        prev = prices[-1 - lookback]
        if prev is None or prev <= 0:
            return 0.0
        return (prices[-1] / prev) - 1.0

    def composite_momentum(self, prices):
        m1 = self.momentum(prices, 21)
        m3 = self.momentum(prices, 63)
        m6 = self.momentum(prices, 126)
        return 0.35 * m1 + 0.35 * m3 + 0.30 * m6

    def realized_vol(self, prices, lookback=63):
        if len(prices) < lookback + 1:
            return None
        rets = []
        for i in range(
            len(prices) - lookback, len(prices)
        ):
            if prices[i - 1] > 0:
                rets.append(
                    prices[i] / prices[i - 1] - 1.0
                )
        if len(rets) < 20:
            return None
        mean = sum(rets) / len(rets)
        var = sum(
            (r - mean) ** 2 for r in rets
        ) / len(rets)
        ann_vol = math.sqrt(var) * math.sqrt(252)
        if (
            ann_vol <= 0
            or math.isnan(ann_vol)
            or math.isinf(ann_vol)
        ):
            return None
        return ann_vol

    def is_above_sma(
        self, ticker, ohlcv, closes, length
    ):
        try:
            sma = SMA(
                ticker, ohlcv, length=length
            )
            if (
                sma
                and len(sma) > 0
                and sma[-1] is not None
            ):
                return closes[-1] > sma[-1]
        except Exception:
            pass
        return False

    # ============================================================
    # MAIN STRATEGY
    # ============================================================

    def run(self, data):
        allocation = {
            t: 0.0 for t in self.tickers
        }

        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                return TargetAllocation(allocation)

            # ================================================
            # WEEKLY REBALANCE (~every 5 trading days)
            # Surmount OHLCV bars lack date fields,
            # so we approximate Thursday via bar count.
            # On non-rebalance days, hold prior weights.
            # ================================================
            self.bar_count += 1
            if (
                self.bar_count % self.rebalance_freq
                != 0
                and self.last_allocation is not None
            ):
                return TargetAllocation(
                    self.last_allocation
                )

            closes = {
                t: self.get_closes(ohlcv, t)
                for t in self.tickers
            }
            for t in self.tickers:
                if len(closes[t]) < self.min_bars:
                    return TargetAllocation(
                        allocation
                    )

            # ================================================
            # CPI REGIME
            # ================================================
            median_cpi_data = data.get(
                ("median_cpi",)
            )
            latest_cpi = 0.0
            if (
                median_cpi_data
                and len(median_cpi_data) > 0
            ):
                latest_cpi = (
                    median_cpi_data[-1]
                    .get("value", 0.0)
                )
            inflation_on = latest_cpi > 4.0

            # ================================================
            # UNIVERSE SELECTION
            # Inflation: exclude long duration (TLT)
            # Normal: full FI + gold universe
            # ================================================
            if inflation_on:
                candidates = [
                    "TIP", "SHY", "BIL",
                    "HYG", "GLD",
                ]
                safe_haven = "BIL"
            else:
                candidates = [
                    "TLT", "IEF", "LQD",
                    "HYG", "GLD",
                ]
                safe_haven = "SHY"

            # ================================================
            # MOMENTUM RANKING
            # ================================================
            scores = {
                t: self.composite_momentum(
                    closes[t]
                )
                for t in candidates
            }
            ranked = sorted(
                scores.keys(),
                key=lambda t: scores[t],
                reverse=True,
            )

            # Absolute momentum gate:
            # 3-month return must be positive
            positive = [
                t for t in ranked
                if self.momentum(closes[t], 63) > 0
            ]

            # Trend gate: price above 50-day SMA
            # (faster than 100-day — catches exits
            #  sooner, safe at weekly frequency)
            confirmed = [
                t for t in positive
                if self.is_above_sma(
                    t, ohlcv, closes[t], 50
                )
            ]

            # ================================================
            # DRAWDOWN BRAKE
            # If ZERO candidates have positive 21-day
            # momentum, everything is selling off.
            # Override to full defense immediately.
            # This is the circuit breaker for the
            # 2026-style correlated drawdown.
            # ================================================
            any_short_positive = any(
                self.momentum(closes[t], 21) > 0
                for t in candidates
            )
            if not any_short_positive:
                confirmed = []

            # ================================================
            # INVERSE-VOL WEIGHTING
            # ================================================
            def inv_vol_weights(assets):
                vols = {}
                for t in assets:
                    v = self.realized_vol(
                        closes[t], 63
                    )
                    vols[t] = (
                        v if (v and v > 0)
                        else 0.10
                    )
                inv = {
                    t: 1.0 / vols[t]
                    for t in assets
                }
                total = sum(inv.values())
                if total <= 0:
                    eq = 1.0 / len(assets)
                    return {
                        t: eq for t in assets
                    }
                return {
                    t: inv[t] / total
                    for t in assets
                }

            # ================================================
            # ALLOCATION TIERS
            # ================================================
            if len(confirmed) >= 3:
                hold = confirmed[:3]
                weights = inv_vol_weights(hold)
            elif len(confirmed) == 2:
                hold = confirmed[:2]
                w = inv_vol_weights(hold)
                weights = {
                    t: v * 0.80
                    for t, v in w.items()
                }
                weights[safe_haven] = (
                    weights.get(safe_haven, 0)
                    + 0.20
                )
            elif len(confirmed) == 1:
                weights = {
                    confirmed[0]: 0.40,
                    safe_haven: 0.60,
                }
            else:
                # Full defense — split between
                # safe haven and ultra-short cash
                if safe_haven == "BIL":
                    weights = {"BIL": 1.0}
                else:
                    weights = {
                        safe_haven: 0.60,
                        "BIL": 0.40,
                    }

            # ================================================
            # APPLY & NORMALIZE
            # ================================================
            for t, w in weights.items():
                if t in allocation:
                    allocation[t] = round(w, 4)

            total = sum(allocation.values())
            if total > 1.0:
                allocation = {
                    k: v / total
                    for k, v in allocation.items()
                }

            self.last_allocation = dict(
                allocation
            )

            held = [
                (t, round(w, 3))
                for t, w in allocation.items()
                if w > 0
            ]
            log(f"Hold: {held}")
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Error: {e}")
            return TargetAllocation(allocation)