from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Asset Universes based on Hybrid Asset Allocation (HAA)
        self.offensive_assets = ["SPY", "IWM", "VEA", "VWO", "VNQ", "DBC", "IEF", "TLT"]
        self.canary_asset = "TIP"
        self.defensive_asset = "BIL"
        
        # Aggregate all unique tickers needed for data fetching
        self.tickers = self.offensive_assets + [self.canary_asset, self.defensive_asset]
        self.data_list = []

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Daily data is sufficient for a long-term momentum allocation strategy
        return "1day"
        
    @property
    def data(self):
        return self.data_list

    def calculate_momentum(self, ticker, data):
        """
        Calculates the average of 1, 3, 6, and 12-month returns.
        Approximated as 21, 63, 126, and 252 trading days.
        """
        # Edge case: Insufficient data history
        if len(data) < 252:
            return None
        
        # Retrieve historical closes
        p_curr = data[-1][ticker]["close"]
        p_1m = data[-21][ticker]["close"]
        p_3m = data[-63][ticker]["close"]
        p_6m = data[-126][ticker]["close"]
        p_12m = data[-252][ticker]["close"]
        
        # Calculate individual timeframe returns
        ret_1m = (p_curr / p_1m) - 1
        ret_3m = (p_curr / p_3m) - 1
        ret_6m = (p_curr / p_6m) - 1
        ret_12m = (p_curr / p_12m) - 1
        
        # Return the blended momentum score
        return (ret_1m + ret_3m + ret_6m + ret_12m) / 4.0

    def run(self, data):
        ohlcv = data["ohlcv"]
        
        # Initialize target allocation with 0 for all assets
        allocation = {ticker: 0.0 for ticker in self.tickers}
        
        # Edge case: Need at least 252 days of data to calculate the 12-month return
        if len(ohlcv) < 252:
            log("Insufficient data to calculate 12-month momentum. Defaulting to defensive asset.")
            allocation[self.defensive_asset] = 1.0
            return TargetAllocation(allocation)
            
        # 1. Check the Canary (TIPS)
        tip_momentum = self.calculate_momentum(self.canary_asset, ohlcv)
        
        if tip_momentum is None:
            allocation[self.defensive_asset] = 1.0
            return TargetAllocation(allocation)
            
        log(f"TIP Canary Momentum: {tip_momentum:.4f}")
        
        # 2. Strategy Routing
        if tip_momentum <= 0:
            # CRASH PROTECTION: Canary momentum is negative.
            # Allocate 100% to the defensive asset (BIL / Cash equivalent)
            log("Canary indicates downtrend. Shifting 100% to defensive asset.")
            allocation[self.defensive_asset] = 1.0
            
        else:
            # OFFENSIVE MODE: Canary momentum is positive.
            # Calculate momentum for all offensive assets
            offensive_momenta = {}
            for asset in self.offensive_assets:
                mom = self.calculate_momentum(asset, ohlcv)
                if mom is not None:
                    offensive_momenta[asset] = mom
                    
            # Filter assets with positive momentum and sort descending
            positive_assets = {k: v for k, v in offensive_momenta.items() if v > 0}
            sorted_assets = sorted(positive_assets.keys(), key=lambda x: positive_assets[x], reverse=True)
            
            # Select the top 4 assets (or fewer if less than 4 have positive momentum)
            top_assets = sorted_assets[:4]
            
            if len(top_assets) == 0:
                # If no offensive assets have positive momentum, default to defensive
                log("No offensive assets with positive momentum. Shifting to defensive asset.")
                allocation[self.defensive_asset] = 1.0
            else:
                # Allocate equally among the top assets (25% max per asset)
                weight_per_asset = 0.25
                for asset in top_assets:
                    allocation[asset] = weight_per_asset
                    log(f"Allocating {weight_per_asset*100}% to {asset} (Mom: {offensive_momenta[asset]:.4f})")
                
                # If there are fewer than 4 positive assets, the remainder goes to the defensive asset
                remaining_weight = 1.0 - (len(top_assets) * weight_per_asset)
                if remaining_weight > 0:
                    allocation[self.defensive_asset] = remaining_weight
                    log(f"Allocating remainder {remaining_weight*100}% to {self.defensive_asset}")

        return TargetAllocation(allocation)