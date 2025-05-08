from surmount.base_class import Strategy, TargetAllocation
from datetime import datetime
import pytz

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = ["QQQ"]

    @property
    def assets(self):
        return self.tickers
    
    @property
    def interval(self):
        return "1day"
    
    def run(self, data):
        # Initialize the allocation with no positions
        allocation = {"QQQ": 0}
        
        # Use the Eastern Time Zone to align with major U.S. markets
        eastern = pytz.timezone("US/Eastern")
        today = datetime.now(eastern).date()

        # Since we're using "1day" interval, we act based on yesterday's data
        # If yesterday was Monday, we are now on Tuesday, so buy QQQ (market closed)
        if today.weekday() == 1:  # It's Tuesday, meaning we just passed Monday
            allocation["QQQ"] = 1
        # If yesterday was Wednesday, we're now on Thursday, so sell QQQ
        elif today.weekday() == 3:  # It's Thursday
            allocation["QQQ"] = 0
                
        return TargetAllocation(allocation)