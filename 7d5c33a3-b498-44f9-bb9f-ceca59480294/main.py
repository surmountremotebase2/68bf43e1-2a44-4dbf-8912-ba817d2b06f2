from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.data import Asset

class TradingStrategy(Strategy):
    def __init__(self):
        # Initialize with the stock ticker you want to trade
        self.ticker = "AAPL"

    @property
    def assets(self):
        # Return a list of assets the strategy will handle
        return [self.ticker]

    @property
    def interval(self):
        # Define the data interval to use for calculations
        return "1day"

    def run(self, data):
        # Extract closing prices
        closes = [d[self.ticker]["close"] for d in data["ohlcv"]]
        
        # Calculate the 50-day SMA
        sma_50 = SMA(self.ticker, data["ohlcv"], 50)
        
        # Determine the last closing price
        latest_close = closes[-1]

        # Initialize the allocation dictionary
        allocation_dict = {self.ticker: 0}

        # Check if we have at least 50 days of data
        if len(closes) >= 50:
            # Compare the latest close to the SMA to determine the trend
            if latest_close > sma_50[-1]:
                # If the latest close is above the SMA, set allocation to 1 (buy)
                allocation_dict[self.ticker] = 1
            elif latest_close < sma_50[-1]:
                # If the latest close is below the SMA, keep allocation at 0 (sell/hold)
                allocation_dict[self.ticker] = 0

        # Return the target allocation
        return TargetAllocation(allocation_dict)