from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from datetime import datetime

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the ticker for the asset we are interested in.
        self.ticker = "QQQ"
    
    @property
    def assets(self):
        # Return a list of assets the strategy will trade.
        return [self.ticker]

    @property
    def interval(self):
        # The strategy will use daily data points for decision making.
        return "1day"
    
    @property
    def data(self):
        # No additional data sources are required for this simple strategy.
        return []
    
    def run(self, data):
        # Initialize the target allocation for QQQ to zero.
        qqq_stake = 0
        
        # Get the current date in the 'yyyy-mm-dd' format.
        current_date = datetime.today().strftime('%Y-%m-%d')
        
        # Determine the current day of the week (0=Monday, 6=Sunday).
        day_of_week = datetime.today().weekday()
        
        # If today is Monday, set the allocation to buy QQQ.
        if day_of_week == 0:  # Monday
            qqq_stake = 1  # Buy QQQ
        elif day_of_week == 2:  # Wednesday
            qqq_stake = 0  # Sell QQQ (by setting allocation to 0)
            
        # Log the action for debugging purposes.
        log(f"QQQ allocation on {current_date}: {qqq_stake}")
        
        # Return the target allocation for this strategy run.
        return TargetAllocation({self.ticker: qqq_stake})