from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.data import MedianCPI
from surmount.logging import log
import math


class TradingStrategy(Strategy):

    def __init__(self):
        self.tickers = [
            "TLT",  # Long-term treasuries (duration)
            "IEF",  # Intermediate treasuries (core)
            "TIP",  # TIPS (inflation hedge)
            "SHY",  # Short-term treasuries (cash proxy)
            "HYG",  # High yield corporate (credit)
            "CWB",  # Convertible bonds (credit + equity beta)
            "GLD",  # Gold (inflation + tail risk hedge)
        ]
        self.data_list = [MedianCPI()]
        self.min_bars = 140
        self.warmup = 1

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
        """
        Blended 1m / 3m / 6m momentum.
        Shorter windows make it responsive;
        longer windows suppress whipsaw.
        """
        m1 = self.momentum(prices, 21)
        m3 = self.momentum(prices, 63)
        m6 = self.momentum(prices, 126)
        return 0.35 * m1 + 0.35 * m3 + 0.30 * m6

    def realized_vol(self, prices, lookback=63):
        if len(prices) < lookback + 1:
            return None
        rets = []
        for i in range(len(prices) - lookback, len(prices)):
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
        self, ticker, ohlcv, closes, length=100
    ):
        try:
            sma = SMA(ticker, ohlcv, length=length)
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

            closes = {
                t: self.get_closes(ohlcv, t)
                for t in self.tickers
            }

            for t in self.tickers:
                if len(closes[t]) < self.min_bars:
                    return TargetAllocation(allocation)

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
            # ================================================
            # Inflation regime excludes long duration
            # (TLT gets crushed when rates rise)
            if inflation_on:
                candidates = [
                    "TIP", "SHY", "HYG", "GLD"
                ]
                safe_haven = "SHY"
            else:
                candidates = [
                    "TLT", "IEF", "HYG",
                    "CWB", "GLD"
                ]
                safe_haven = "IEF"

            # ================================================
            # MOMENTUM RANKING
            # ================================================
            scores = {}
            for t in candidates:
                scores[t] = self.composite_momentum(
                    closes[t]
                )

            ranked = sorted(
                scores.keys(),
                key=lambda t: scores[t],
                reverse=True,
            )

            # ================================================
            # ABSOLUTE MOMENTUM FILTER
            # Only hold assets with positive 3m return.
            # This is the key mechanism that avoids
            # holding losing positions for weeks.
            # ================================================
            positive = [
                t for t in ranked
                if self.momentum(closes[t], 63) > 0
            ]

            # ================================================
            # TREND CONFIRMATION (100-day SMA)
            # Shorter than 200 — bonds trend faster
            # than equities, 200 is too lagging.
            # ================================================
            confirmed = [
                t for t in positive
                if self.is_above_sma(
                    t, ohlcv, closes[t], 100
                )
            ]

            # ================================================
            # INVERSE-VOL WEIGHTING
            # Lower-vol assets get more weight,
            # higher-vol assets get less.
            # This is the vol targeting replacement.
            # ================================================
            def inv_vol_weights(assets, fallback_w):
                """
                Allocate budget proportional to
                1/vol for each selected asset.
                """
                vols = {}
                for t in assets:
                    v = self.realized_vol(
                        closes[t], 63
                    )
                    if v and v > 0:
                        vols[t] = v
                    else:
                        vols[t] = 0.10  # fallback
                inv = {
                    t: 1.0 / vols[t]
                    for t in assets
                }
                total_inv = sum(inv.values())
                if total_inv <= 0:
                    return {
                        t: fallback_w
                        for t in assets
                    }
                return {
                    t: inv[t] / total_inv
                    for t in assets
                }

            # ================================================
            # ALLOCATION TIERS
            # ================================================
            if len(confirmed) >= 3:
                # Top 3 by momentum, inv-vol weighted
                hold = confirmed[:3]
                weights = inv_vol_weights(hold, 0.33)
            elif len(confirmed) == 2:
                hold = confirmed[:2]
                w = inv_vol_weights(hold, 0.40)
                # Scale to 80%, 20% to safe haven
                weights = {
                    t: v * 0.80 for t, v in w.items()
                }
                weights[safe_haven] = (
                    weights.get(safe_haven, 0) + 0.20
                )
            elif len(confirmed) == 1:
                weights = {
                    confirmed[0]: 0.40,
                    safe_haven: 0.60,
                }
            else:
                # Nothing trending — full defensive
                if safe_haven == "SHY":
                    weights = {"SHY": 1.0}
                else:
                    weights = {
                        safe_haven: 0.70,
                        "SHY": 0.30,
                    }

            # ================================================
            # APPLY
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