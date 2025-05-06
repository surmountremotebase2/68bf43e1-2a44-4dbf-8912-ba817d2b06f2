from surmount.base_class import Strategy, TargetAllocation
from surmount.data import ohlcv
from datetime import datetime, timedelta

class TradingStrategy(Strategy):
    def __init__(self):
        # Define which ticker we're interested in trading
        self.tickers = ["QQQ"]
    
    @property
    def assets(self):
        # The assets that the strategy trades
        return self.tickers
    
    @property
    def interval(self):
        # Define the interval for data refresh, 1day for daily checks
        return "1day"
    
    def run(self, data):
        # Initialize the allocation for QQQ to 0
        allocation = {"QQQ": 0}
        
        # Check if we have OHLCV data for QQQ
        if "QQQ" in data["ohlcv"]:
            # Get today's datetime object
            today = datetime.now()
            # If today is Monday, we buy QQQ at market close, so we set the allocation to 1
            if today.weekday() == 0:  # Python's datetime.weekday() returns 0 for Monday
                allocation["QQQ"] = 1
            # If today is Wednesday and it's market open, we sell QQQ by setting allocation to 0
            # Since we are using "1day" interval data, we don't have the exact opening time.
            # We assume this strategy is evaluated right at or just before the open.
            elif today.weekday() == 2:  # Wednesday
                allocation["QQQ"] = 0
                
        return TargetAllocation(allocation)