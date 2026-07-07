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
        self.min_bars = 150
        self.warmup = 1
        
        # INCREASED LOOKBACK: Shift from weekly (5) to Monthly (21) 
        # dramatically lowers trading frequency and eliminates noise whipsaws
        self.rebalance_freq = 21 
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
    # QUANT HELPERS
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

    def momentum(self, prices, lookback):
        if len(prices) <= lookback:
            return 0.0
        prev = prices[-1 - lookback]
        if prev is None or prev <= 0:
            return 0.0
        return (prices[-1] / prev) - 1.0

    def composite_momentum(self, prices):
        # Re-weighted to favor intermediate/long-term trend persistence in Fixed Income
        m1 = self.momentum(prices, 21)
        m3 = self.momentum(prices, 63)
        m6 = self.momentum(prices, 126)
        return 0.20 * m1 + 0.40 * m3 + 0.40 * m6

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

    def is_above_sma(self, ticker, ohlcv, closes, length):
        try:
            sma = SMA(ticker, ohlcv, length=length)
            if sma and len(sma) > 0 and sma[-1] is not None:
                return closes[-1] > sma[-1]
        except Exception:
            pass
        return False

    # ============================================================
    # EXECUTION ENGINE
    # ============================================================

    def run(self, data):
        allocation = {t: 0.0 for t in self.tickers}

        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                return TargetAllocation(allocation)

            # Monthly Rebalance Sentinel
            self.bar_count += 1
            if self.bar_count % self.rebalance_freq != 0 and self.last_allocation is not None:
                return TargetAllocation(self.last_allocation)

            closes = {t: self.get_closes(ohlcv, t) for t in self.tickers}
            for t in self.tickers:
                if len(closes[t]) < self.min_bars:
                    return TargetAllocation(allocation)

            # ================================================
            # DYNAMIC INFLATION REGIME SWITCHING
            # ================================================
            median_cpi_data = data.get(("median_cpi",))
            inflation_on = False
            
            if median_cpi_data and len(median_cpi_data) >= 4:
                latest_cpi = median_cpi_data[-1].get("value", 0.0)
                # Compare against 3 months ago to discover directional velocity
                three_month_ago_cpi = median_cpi_data[-4].get("value", 0.0)
                
                # Inflation is ON if it is structural (above 3.5%) AND accelerating
                if latest_cpi > 3.5 and latest_cpi >= three_month_ago_cpi:
                    inflation_on = True
            elif median_cpi_data and len(median_cpi_data) > 0:
                # Fallback safeguard
                inflation_on = median_cpi_data[-1].get("value", 0.0) > 4.0

            # ================================================
            # UNIVERSE SELECTION
            # ================================================
            if inflation_on:
                candidates = ["TIP", "SHY", "BIL", "HYG", "GLD"]
                safe_haven = "BIL"
            else:
                candidates = ["TLT", "IEF", "LQD", "HYG", "GLD"]
                safe_haven = "IEF" # Upgraded to IEF for better yield generation when regime is safe

            # ================================================
            # SYSTEMATIC TREND & MOMENTUM GATES
            # ================================================
            scores = {t: self.composite_momentum(closes[t]) for t in candidates}
            ranked = sorted(scores.keys(), key=lambda t: scores[t], reverse=True)

            # Absolute Momentum Gate (Medium-term structural health)
            positive = [t for t in ranked if self.momentum(closes[t], 63) > 0]

            # Dynamic Trend Gate: Smoothed to 100-day SMA to reduce noise whipsaws
            confirmed = [t for t in positive if self.is_above_sma(t, ohlcv, closes[t], 100)]

            # ================================================
            # CORRELATED DRAWDOWN BRAKE (RE-CALIBRATED)
            # ================================================
            # Look at a broader 42-day window (2 months) to avoid cutting exposure on minor noise
            any_medium_positive = any(self.momentum(closes[t], 42) > 0 for t in candidates)
            if not any_medium_positive:
                confirmed = []

            # ================================================
            # RISK-PARITY WEIGHTING METRIC
            # ================================================
            def inv_vol_weights(assets):
                vols = {}
                for t in assets:
                    v = self.realized_vol(closes[t], 63)
                    vols[t] = v if (v and v > 0) else 0.08
                
                inv = {t: 1.0 / vols[t] for t in assets}
                total = sum(inv.values())
                if total <= 0:
                    eq = 1.0 / len(assets)
                    return {t: eq for t in assets}
                return {t: inv[t] / total for t in assets}

            # ================================================
            # ALLOCATION TIERS
            # ================================================
            if len(confirmed) >= 3:
                hold = confirmed[:3]
                weights = inv_vol_weights(hold)
            elif len(confirmed) == 2:
                hold = confirmed[:2]
                w = inv_vol_weights(hold)
                weights = {t: v * 0.85 for t, v in w.items()}
                weights[safe_haven] = weights.get(safe_haven, 0) + 0.15
            elif len(confirmed) == 1:
                weights = {confirmed[0]: 0.50, safe_haven: 0.50}
            else:
                # Full Defensive State
                if safe_haven == "BIL":
                    weights = {"BIL": 1.0}
                else:
                    weights = {"IEF": 0.50, "BIL": 0.50}

            # ================================================
            # POST-PROCESSING & NORMALIZATION
            # ================================================
            for t, w in weights.items():
                if t in allocation:
                    allocation[t] = round(w, 4)

            total = sum(allocation.values())
            if total > 1.0 or total < 0.999:
                if total > 0:
                    allocation = {k: v / total for k, v in allocation.items()}

            self.last_allocation = dict(allocation)
            
            held = [(t, round(w, 3)) for t, w in allocation.items() if w > 0]
            log(f"Holdings Update: {held}")
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Execution Error: {e}")
            return TargetAllocation(allocation)