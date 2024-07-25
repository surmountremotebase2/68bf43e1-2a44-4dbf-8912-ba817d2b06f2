from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB, ATR
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # The tickers list contains a placeholder for VIX futures; replace "VIX_FUTURE" with actual ticker code
        self.tickers = ["VIX_FUTURE"]
    
    @property
    def interval(self):
        # Trades are evaluated on a daily basis for this strategy
        return "1day"
    
    @property
    def assets(self):
        # This strategy trades VIX futures
        return self.tickers
    
    def run(self, data):
        # Allocate no initial position; adjustments will be made based on indicators
        allocation_dict = {tick: 0 for tick in self.tickers}
        
        # Check that we have sufficient historical data for analysis
        if len(data["ohlcv"]) < 21:  # Assuming we need at least 21 days for the ATR and BB calculations
            return TargetAllocation(allocation_dict)
        
        # Calculate Bollinger Bands and ATR for the VIX futures
        bb = BB("VIX_FUTURE", data["ohlcv"], 20, 2)  # 20 days, 2 standard deviations
        atr = ATR("VIX_FUTURE", data["ohlcv"], 14)  # 14 days typical for ATR

        # Latest closing price of VIX futures
        latest_close = data["ohlcv"][-1]["VIX_FUTURE"]["close"]

        # Strategy Logic:
        # If the latest close is above the upper Bollinger band, it signals increased volatility; go long on VIX futures.
        # If the latest close is below the lower Bollinger band, it signals decreased volatility; possibly go short on VIX futures or close position depending on risk management preferences.
        # ATR is used for position sizing to manage risk.

        if latest_close > bb["upper"][-1]:
            log("Increasing volatility, going long on VIX futures")
            allocation_dict["VIX_FUTURE"] = 1.0  # Placeholder for position size, adjust based on risk management

        elif latest_close < bb["lower"][-1]:
            log("Decreasing volatility, reducing position on VIX futures")
            allocation_dict["VIX_FUTURE"] = 0  # Close or reduce position as preferred

        # Otherwise, maintain current positions without any adjustment
        else:
            log("Market volatility within expected range; no action taken")
        
        return TargetAllocation(allocation_dict)