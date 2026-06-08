from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the target asset for the ORB strategy
        self.ticker = "QQQ"

    @property
    def assets(self):
        """Returns the list of assets tracked by this strategy."""
        return [self.ticker]

    @property
    def interval(self):
        """Using 1-hour intervals to capture the opening range structure cleanly."""
        return "1hour"

    def run(self, data):
        """
        Executes the logic for the Opening Range Breakout (ORB) strategy.
        Identifies the first candle of the current trading day to set High/Low boundaries,
        then checks subsequent intraday candles for breakout confirmations.
        """
        ohlcv_list = data["ohlcv"]
        ticker = self.ticker
        
        # Edge case: Ensure there is enough historical data to analyze
        if len(ohlcv_list) < 1:
            return TargetAllocation({ticker: 0})
            
        # Get the current bar's data and isolate the current date string (YYYY-MM-DD)
        current_bar = ohlcv_list[-1][ticker]
        current_date_str = current_bar["date"].split(" ")[0] 
        
        # Filter all candles belonging strictly to the current trading day
        current_day_bars = []
        for bar in ohlcv_list:
            if bar[ticker]["date"].startswith(current_date_str):
                current_day_bars.append(bar[ticker])
        
        # Edge case: If this is the first bar of the day, we are currently establishing 
        # the opening range boundaries. No trades can be placed yet.
        if len(current_day_bars) <= 1:
            log(f"Establishing opening range boundaries for {current_date_str}")
            return TargetAllocation({ticker: 0})
        
        # Define the Opening Range boundaries using the first bar of the session
        opening_bar = current_day_bars[0]
        opening_high = opening_bar["high"]
        opening_low = opening_bar["low"]
        
        current_close = current_bar["close"]
        allocation = 0.0
        
        # --- ORB Execution Logic ---
        # 1. Bullish Breakout: If the current close breaks above the opening high, go long.
        if current_close > opening_high:
            log(f"ORB Bullish Breakout Confirmed: Close ({current_close}) > Opening High ({opening_high})")
            allocation = 1.0
            
        # 2. Bearish Breakdown / Stop Loss: If the price falls below the opening low, stay out.
        elif current_close < opening_low:
            log(f"ORB Bearish Breakdown/Stop Out: Close ({current_close}) < Opening Low ({opening_low})")
            allocation = 0.0
            
        # 3. Inside Range: If the current price is inside the opening range, check if we 
        # broke out in the previous hour to maintain the trend holding state.
        else:
            prev_bar = current_day_bars[-2]
            if prev_bar["close"] > opening_high:
                log("Maintaining active long position from prior breakout hour.")
                allocation = 1.0
            else:
                allocation = 0.0

        # Return the finalized target allocation dictionary wrapped inside TargetAllocation
        return TargetAllocation({ticker: allocation})