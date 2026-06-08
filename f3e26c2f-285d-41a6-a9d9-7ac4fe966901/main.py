from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import VWAP
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the target asset for the ORB strategy
        self.ticker = "TQQQ"

    @property
    def assets(self):
        """Returns the list of assets tracked by this strategy."""
        return [self.ticker]

    @property
    def interval(self):
        """Using 1-hour intervals for clear intraday opening range definitions."""
        return "1hour"

    def run(self, data):
        """
        Executes the logic for the Opening Range Breakout (ORB) strategy
        coupled with a 100-bar VWAP regime trend filter.
        """
        ohlcv_list = data["ohlcv"]
        ticker = self.ticker
        
        # Ensure we have enough bars to calculate the 100-period VWAP 
        # and capture the session's historical backdrop.
        if ohlcv_list is None or len(ohlcv_list) < 1:
            return TargetAllocation({ticker: 0})
            
        # Get current candle details
        current_bar = ohlcv_list[-1][ticker]
        current_close = current_bar["close"]
        current_date_str = current_bar["date"].split(" ")[0] 
        
        # =====================================================
        # 100-BAR VWAP TREND FILTER REGIME
        # =====================================================
        try:
            vwap_series = VWAP(ticker, ohlcv_list, length=100)
            
            # Defensive check for invalid indicator structures
            if vwap_series is None or len(vwap_series) == 0 or vwap_series[-1] is None:
                log(f"Insufficient or invalid VWAP data for {ticker}. Remaining flat.")
                return TargetAllocation({ticker: 0})
                
            latest_vwap = vwap_series[-1]
            
        except Exception as e:
            log(f"Error calculating VWAP indicator: {str(e)}")
            return TargetAllocation({ticker: 0})

        # Filter all candles belonging strictly to the current day's market session
        current_day_bars = []
        for bar in ohlcv_list:
            if bar[ticker]["date"].startswith(current_date_str):
                current_day_bars.append(bar[ticker])
        
        # Edge Case: If this is the first bar of the day, we are mapping the opening range.
        if len(current_day_bars) <= 1:
            #log(f"Mapping initial opening range boundaries for session: {current_date_str}")
            return TargetAllocation({ticker: 0})
        
        # Establish Opening Range limits using the session's first candle
        opening_bar = current_day_bars[0]
        opening_high = opening_bar["high"]
        opening_low = opening_bar["low"]
        
        allocation = 0.0

        # =====================================================
        # CORE EXECUTION LOGIC WITH VWAP FILTER
        # =====================================================
        
        if current_close > opening_high and current_close < latest_vwap:
            #log(f"ORB Long Confirmed: Close ({current_close}) > Opening High ({opening_high}) & Above VWAP.")
            allocation = 1.0
            
        # Bearish Breakdown: Close drops underneath the opening range lower boundaries
        #elif current_close < opening_low:
            #log(f"ORB Bearish Breakdown: Close ({current_close}) < Opening Low ({opening_low}). Staying Flat.")
            #allocation = 0.0
            
        # Inside Range State-Machine: Check whether we broken out earlier in the day to hold the position
        else:
            prev_bar = current_day_bars[-2]
            # Maintain long position only if the previous hour was an active breakout state 
            # AND we remain securely above the 100-period VWAP filter benchmark.
            if prev_bar["close"] > opening_high and current_close < latest_vwap:
                #log("Maintaining active macro-supported breakout position inside the range.")
                allocation = 1.0
            else:
                allocation = 0.0

        return TargetAllocation({ticker: allocation})