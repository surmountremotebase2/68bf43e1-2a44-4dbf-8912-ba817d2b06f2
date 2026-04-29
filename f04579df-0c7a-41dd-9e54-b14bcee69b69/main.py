from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log

class TradingStrategy(Strategy):
    @property
    def assets(self):
        # Using QQQ for Longs and SQQQ for Shorts to handle bidirectional trading
        return ["QQQ", "SQQQ"]

    @property
    def interval(self):
        return "1hour"

    def run(self, data):
        ohlcv = data["ohlcv"]
        
        # Need enough data to look back a full trading day (approx 7 hourly bars)
        if len(ohlcv) < 8:
            return TargetAllocation({})

        qqq_alloc = 0.0
        sqqq_alloc = 0.0

        # Get the timestamp of the latest completed bar
        current_time_str = ohlcv[-1]["QQQ"]["date"]
        current_price = ohlcv[-1]["QQQ"]["close"]

        # --- 1. END OF DAY EXIT ---
        # If it's the end of the trading day, flatten positions to avoid overnight risk
        if "15:30" in current_time_str or "16:00" in current_time_str:
            return TargetAllocation({"QQQ": 0.0, "SQQQ": 0.0})

        # --- 2. IDENTIFY THE OPENING RANGE ---
        # Look back over the last few bars to find today's 09:30 candle
        today_str = current_time_str.split(" ")[0]
        first_candle = None

        for i in range(1, 8):
            candle_date = ohlcv[-i]["QQQ"]["date"]
            if today_str in candle_date and "09:30" in candle_date:
                first_candle = ohlcv[-i]["QQQ"]
                break

        # If we are currently IN the first hour, or missing data, do nothing
        if first_candle is None or current_time_str == first_candle["date"]:
            return TargetAllocation({"QQQ": 0.0, "SQQQ": 0.0})

        or_open = first_candle["open"]
        or_close = first_candle["close"]
        or_high = first_candle["high"]
        or_low = first_candle["low"]

        # --- 3. PARAMETERS (Matching your script) ---
        target_R = 2.0        # Reward to Risk ratio
        target_risk_pct = 0.02 # Risking 2% of portfolio max per trade

        # --- 4. STRATEGY LOGIC & SIZING ---
        if or_close > or_open:
            # LONG BIAS (Opening Range closed green)
            stop_price = or_low
            risk_dollars = or_close - stop_price
            target_price = or_close + (risk_dollars * target_R)

            # Dynamic Sizing: Match allocation so that if stop is hit, we lose ~2%
            stop_distance_pct = abs(risk_dollars) / or_close if or_close != 0 else 0.001
            alloc_size = min(1.0, target_risk_pct / stop_distance_pct)

            # Execution: Check if Stop Loss or Take Profit was triggered
            if current_price <= stop_price or current_price >= target_price:
                qqq_alloc = 0.0 # Exit trade
            else:
                qqq_alloc = alloc_size # Enter or Hold Long

        elif or_close < or_open:
            # SHORT BIAS (Opening Range closed red) -> Use SQQQ
            stop_price = or_high
            risk_dollars = stop_price - or_close
            target_price = or_close - (risk_dollars * target_R)

            # Dynamic Sizing
            stop_distance_pct = abs(risk_dollars) / or_close if or_close != 0 else 0.001
            alloc_size = min(1.0, target_risk_pct / stop_distance_pct)

            # Execution: Check if Stop Loss or Take Profit was triggered
            if current_price >= stop_price or current_price <= target_price:
                sqqq_alloc = 0.0 # Exit trade
            else:
                sqqq_alloc = alloc_size # Enter or Hold Short

        return TargetAllocation({"QQQ": qqq_alloc, "SQQQ": sqqq_alloc})