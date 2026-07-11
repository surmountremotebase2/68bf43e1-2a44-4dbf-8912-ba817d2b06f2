from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.data import MedianCPI
from surmount.logging import log
import math

class TradingStrategy(Strategy):

    def __init__(self):
        # We add XLU to fetch the data, but we won't allocate to it.
        # This keeps the strategy purely Fixed Income & Gold focused.
        self.tickers = [
            "TLT",  # Long-term treasuries (20+ yr)
            "AGG",  # Agg US Bonds
            "BND",  # Total Bond Mrkt
            "MUB",  # Municipal Bonds
            "VWOB", # Emerging Mrkt Govt Bonds
            "UUP",  # US Dollar Index
            "IEF",  # Intermediate treasuries (7-10 yr)
            "LQD",  # Investment grade corporate
            "TIP",  # TIPS (inflation hedge)
            "HYG",  # High yield corporate
            "SHY",  # Short-term treasuries (1-3 yr)
            "BIL",  # Ultra-short T-Bills (1-3 mo)
            "GLD",  # Gold (tail-risk hedge)
            "XLU",  # Utilities Sector (Used for Ratio ONLY)
        ]
        self.investable_assets = [t for t in self.tickers if t != "XLU"]
        
        self.data_list = [MedianCPI()]
        self.min_bars = 100
        self.warmup = 1
        
        # Monthly Rebalance (~21 trading days) to minimize turnover drag
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
        m1 = self.momentum(prices, 63)
        m3 = self.momentum(prices, 126)
        m6 = self.momentum(prices, 252)
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
        allocation = {t: 0.0 for t in self.investable_assets}

        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                return TargetAllocation(allocation)

            # Monthly Rebalance Gate
            self.bar_count += 1
            if self.bar_count % self.rebalance_freq != 0 and self.last_allocation is not None:
                return TargetAllocation(self.last_allocation)

            closes = {t: self.get_closes(ohlcv, t) for t in self.tickers}
            for t in self.tickers:
                if len(closes[t]) < self.min_bars:
                    return TargetAllocation(allocation)

            # ================================================
            # XLU/TLT REGIME FILTER (The Core Engine)
            # ================================================
            # Align price arrays to handle any missing internal bars safely
            min_len = min(len(closes["XLU"]), len(closes["TLT"]))
            
            # Generate the Ratio array (XLU / TLT)
            xlu_tlt_ratio = [
                x / t for x, t in zip(
                    closes["XLU"][-min_len:], 
                    closes["TLT"][-min_len:]
                )
            ]
            
            # Use 63-day (3-month) momentum of the ratio to dictate the regime
            ratio_momentum = self.momentum(xlu_tlt_ratio, 63)
            risk_on_regime = ratio_momentum > 0

            # Dynamic CPI check as a secondary override
            inflation_accelerating = False
            median_cpi_data = data.get(("median_cpi",))
            if median_cpi_data and len(median_cpi_data) >= 3:
                latest_cpi = median_cpi_data[-1].get("value", 0.0)
                three_mo_cpi = median_cpi_data[-4].get("value", 0.0)
                if latest_cpi > 3 and latest_cpi >= three_mo_cpi:
                    inflation_accelerating = True

            # ================================================
            # UNIVERSE SELECTION (Regime Dependent)
            # ================================================
            if inflation_accelerating:
                # Structural Inflation overrides everything
                candidates = ["TIP", "SHY", "UUP", "GLD"]
                safe_haven = "BIL"
            elif risk_on_regime:
                # Utilities outperforming Bonds: Rates likely stable/rising, credit thrives
                candidates = ["HYG", "LQD", "AGG", "BND"]
                safe_haven = "SHY"
            else:
                # Bonds outperforming Utilities: Rates falling, duration thrives
                candidates = ["TLT", "LQD", "AGG", "BND"]
                safe_haven = "IEF"

            # ================================================
            # SYSTEMATIC TREND & MOMENTUM GATES
            # ================================================
            scores = {t: self.composite_momentum(closes[t]) for t in candidates}
            ranked = sorted(scores.keys(), key=lambda t: scores[t], reverse=True)

            positive = [t for t in ranked if self.momentum(closes[t], 63) > 0]
            confirmed = [t for t in positive if self.is_above_sma(t, ohlcv, closes[t], 100)]

            # ================================================
            # CORRELATED DRAWDOWN BRAKE
            # ================================================
            any_medium_positive = any(self.momentum(closes[t], 42) > 0 for t in candidates)
            if not any_medium_positive:
                confirmed = [] # Trigger full defense

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
                    weights = {safe_haven: 0.50, "BIL": 0.50}

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
            log(f"Regime Risk-On: {risk_on_regime} | Inflation Check: {inflation_accelerating}")
            log(f"Holdings: {held}")
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Execution Error: {e}")
            return TargetAllocation(allocation)