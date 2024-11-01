from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self        # Defines a single ticker, SPY for this strategy        
    self.ticker =SPY"

    @property
    def assets(self):
        # a list containing just the SPY ETF, denoting we're only interested in trading SPY.
        return [self.ticker]

    @property
    def interval(self):
        # The interval sets how often this strategy should be evaluated. 
        # Here, "1day" means the strategy will evaluate once daily.
        return "1day"

    def run(self, data):
        # This method dictates the trading logic. For this strategy, since we always want to be
        # fully invested in SPY, we simply allocate 100% of our portfolio to SPY.
        # TargetAllocation expects a dictionary where keys are ticker symbols and values are their
        # corresponding allocation percentages as fractions of 1.
        allocation_dict = {self.ticker: 1.0}  # 100% allocation to SPY

        # Logging purposes, not necessary but useful for debugging.
        log(f"Allocating 100% to {self.ticker}")

        return TargetAllocation(allocation_dict)