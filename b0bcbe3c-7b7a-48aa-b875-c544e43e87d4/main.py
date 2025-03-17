from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.data import Aggregates
import numpy as np

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = ["MRNA", "BNTX", "ISRG", "TDOC", "VRTX", "UNH"]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"  # Monthly rebalancing, but we check daily to apply stop-loss rules.

    def run(self, data):
        allocation_dict = {}
        total_momentum_score = 0
        
        # Calculate Momentum score for each asset (6-month return / sigma)
        for ticker in self.tickers:
            six_month_data = data["ohlcv"][-180:]  # Approximating 6 months with 180 trading days.
            if len(six_month_data) < 180:
                log(f"Not enough data for {ticker}")
                continue

            prices = np.array([day[ticker]["close"] for day in six_month_data])
            returns = np.diff(prices) / prices[:-1]
            sigma = np.std(returns)
            
            # Avoid division by zero
            if sigma == 0:
                momentum_score = 0
            else:
                momentum_score = (prices[-1] - prices[0]) / prices[0] / sigma
            
            allocation_dict[ticker] = momentum_score
            total_momentum_score += momentum_score
        
        # Normalize allocations based on momentum score
        for ticker in allocation_dict:
            allocation_dict[ticker] /= total_momentum_score
            
        # Apply profit-taking and stop-loss rules
        for ticker in self.tickers:
            last_price = data["ohlcv"][-1][ticker]["close"]
            month_ago_price = data["ohlcv"][-30][ticker]["close"] if len(data["ohlcv"]) >= 30 else last_price
            six_month_high = max([day[ticker]["high"] for day in data["ohlcv"][-180:]])

            if ticker in ["MRNA", "BNTX"] and last_price / month_ago_price - 1 > 0.30:
                allocation_dict[ticker] *= 0.8  # Sell 20%
            if last_price < six_month_high * 0.82:  # If dropped more than 18% from recent high
                allocation_dict[ticker] = 0      # Remove it

        # Defensive rotation towards UNH if biotech (MRNA, BNTX) underperforms
        if allocation_dict["MRNA"] + allocation_dict["BNTX"] < 0.2:
            allocation_dict["UNH"] = max(allocation_dict.values())  # Increase allocation to UNH

        # Ensure allocations are within [0, 1]
        allocation_sum = sum(allocation_dict.values())
        if allocation_sum > 1:
            for ticker in allocation_dict:
                allocation_dict[ticker] /= allocation_sum
        
        return TargetAllocation(allocation_dict)