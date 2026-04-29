from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import EMA, ATR
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Long-only basket of ETFs
        self.tickers = ["QQQ", "SPY", "SMH", "GLD"]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # 1-hour bars to capture the opening range
        return "1hour"

    def run(self, data):
        ohlcv = data["ohlcv"]
        allocation_dict = {ticker: 0 for ticker in self.tickers}
        
        # Ensure we have enough data for a 200-period EMA
        if len(ohlcv) < 1:
            return TargetAllocation(allocation_dict)

        # Strategy Parameters
        stop_atr_multiplier = 2.0  # From Section 3: stop_atr
        target_R = 2.0             # Reward to risk ratio
        portfolio_risk = 0.02      # Risk 2% of portfolio per trade
        
        # --- 1. END OF DAY FLATTEN ---
        current_time_str = ohlcv[-1][self.tickers[0]]["date"]
        if "15:30" in current_time_str or "16:00" in current_time_str:
            return TargetAllocation(allocation_dict)

        active_signals = []

        for ticker in self.tickers:
            # 2. TREND FILTER (200 EMA)
            ema_200 = EMA(ticker, ohlcv, 100)
            # 3. VOLATILITY MEASURE (14-period ATR)
            atr_values = ATR(ticker, ohlcv, 14)
            
            if ema_200 is None or atr_values is None:
                continue
                
            # IDENTIFY TODAY'S OPENING RANGE (The 09:30 candle)
            today_str = current_time_str.split(" ")[0]
            first_candle = None
            for i in range(1, 10):
                if today_str in ohlcv[-i][ticker]["date"] and "09:30" in ohlcv[-i][ticker]["date"]:
                    first_candle = ohlcv[-i][ticker]
                    break
            
            if first_candle is None:
                continue

            current_price = ohlcv[-1][ticker]["close"]
            entry_price = ohlcv[-1][ticker]["open"]
            
            # 4. ENTRY CONDITIONS (LONG ONLY)
            # - Price above 200 EMA
            # - Opening hour candle is bullish (Close > Open)
            # - Current price is not already at the end of the day
            if current_price > ema_200[-1] and first_candle["close"] > first_candle["open"]:
                
                # ATR% Calculation: (ATR / Open) lagged
                # Using index -2 for ATR and the opening range candle's open
                atr_percent = atr_values[-2] / first_candle["open"] if first_candle["open"] != 0 else 0
                
                # STOP WIDTH LOGIC: stop_atr * ATR% * (intraday open / entry)
                # We use the Opening Range open as the "intraday open"
                stop_width_pct = stop_atr_multiplier * atr_percent * (first_candle["open"] / entry_price)
                
                stop_price = entry_price * (1 - stop_width_pct)
                target_price = entry_price * (1 + (stop_width_pct * target_R))

                # 5. EXECUTION & RISK SIZING
                # Only allocate if we haven't hit the stop or target
                if current_price > stop_price and current_price < target_price:
                    # Size based on distance to stop (risk parity)
                    # Calculation: Risk Amount / Distance to Stop
                    raw_allocation = portfolio_risk / stop_width_pct if stop_width_pct > 0 else 0
                    active_signals.append({"ticker": ticker, "size": raw_allocation})

        # 6. PORTFOLIO CONSTRUCTION
        # Normalize allocations so the sum doesn't exceed 1.0 (100% margin)
        total_size = sum(s["size"] for s in active_signals)
        if total_size > 0:
            multiplier = min(1.0, 1.0 / total_size)
            for signal in active_signals:
                allocation_dict[signal["ticker"]] = signal["size"] * multiplier

        return TargetAllocation(allocation_dict)