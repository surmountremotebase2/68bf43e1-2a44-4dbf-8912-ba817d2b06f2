from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB, EMA
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = ["NVDA"]
        self.period = 20
        self.std_dev_multiplier = 1.2

    @property
    def assets(self):
        # This strategy focuses on NVDA
        return self.tickers

    @property
    def interval(self):
        # Trading based on hourly data
        return "1hour"

    def run(self, data):
       
        allocation_dict = {}
        allocation_dict["NVDA"] = 1
        
        for ticker in self.tickers:
            # Access historical closing prices for the ticker
            closes = [i[ticker]["close"] for i in data["ohlcv"]]
            # Compute Bollinger Bands components (middle, upper, lower)
            bb = BB(ticker, data["ohlcv"], self.period, self.std_dev_multiplier)
            # Assuming the use of a custom Kalman filter function implemented externally
            ema = EMA(ticker, data["ohlcv"], 5)
    
            current_price = closes[-1]
            upper_band = bb["upper"][-1]
            middle_band = bb["mid"][-1]
            lower_band = bb["lower"][-1]
    
            allocation = 0
            # Condition to enter a trade
            if current_price > upper_band:  # Breakout above upper band
                allocation = 1  # Allocating 100% to buy signal, assuming bullish sentiment
            # Exit trade if price touches the middle band or based on Kalman filter estimation
            elif current_price < ema[-1] and current_price < lower_band:
                allocation = -.1


            if allocation_dict[ticker] == 1 and current_price < ema[-1]:  # Simplified condition
                allocation = 0  # No position
            elif allocation_dict[ticker] == -.1 and current_price > ema[-1]:
                allocation = 0

            allocation_dict[ticker] = allocation

        return TargetAllocation(allocation_dict)