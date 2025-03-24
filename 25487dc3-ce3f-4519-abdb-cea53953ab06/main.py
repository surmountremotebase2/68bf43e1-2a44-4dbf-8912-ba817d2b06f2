from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI, SMA, STDEV
from surmount.logging import log
import pandas as pd
import numpy as np

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the assets the strategy will cover.
        self.tickers = ["SPY"]
        self.allocation = {}
        
    @property
    def interval(self):
        # Use daily data for this strategy.
        return "1day"
        
    @property
    def assets(self):
        # Return the list of assets this strategy applies to.
        return self.tickers
    
    @property
    def data(self):
        # No additional data sources needed for this RSI strategy.
        return []

    def run(self, data):
        # Choose RSI thresholds for buying and selling.
        lower_threshold = 35
        upper_threshold = 85
        
        # Initialize allocation dictionary.
        allocation_dict = {}
        
        
        # Calculating RSI for each asset.
        for ticker in self.tickers:
            rsi_values = RSI(ticker, data["ohlcv"], 10)  # Use a 14-day period for RSI calculation.
            if not rsi_values or len(rsi_values) < 1:
                # If RSI values are unavailable or insufficient, do not allocate.
                allocation_dict[ticker] = 0
            else:
                # Get the most recent RSI value.
                current_rsi = rsi_values[-1]
                
                # Decide on allocation based on RSI.
                if current_rsi < lower_threshold:
                    # If RSI indicates the asset is oversold, allocate a higher percentage to buying it.
                    allocation_dict[ticker] = 1.0
                elif current_rsi > upper_threshold:
                    # If RSI indicates the asset is overbought, allocate zero to buying it.
                    allocation_dict[ticker] = 0
                else:
                    # If RSI indicates the asset is neither overbought nor oversold, maintain a neutral stance.
                    allocation_dict[ticker] = self.allocation
        self.allocation = allocation_dict

        # Return the target allocation for each asset.
        return TargetAllocation(allocation_dict)

# Note:
# This is a basic implementation and may require additional checks and balances for real-world application.
# For instance, incorporating stop-loss levels or adjusting allocations based on portfolio risk management criteria could be beneficial.