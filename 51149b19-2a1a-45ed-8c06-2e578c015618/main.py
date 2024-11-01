from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB
from surmount.logging import log

class TradingStrategy(Strategy):
    @property
    def assets(self):
        # Strategy applies to gcusd
        return ["gcusd"]

    @property
    def interval(self):
        return "1day"

    def run(self, data):
        holdings = data["holdings"]
        data = data["ohlcv"]
        
        #for i in range(len(data)):
        #    data[i]["gcusd"]["open"] = data[i]["gcusd"]["close"]
        
      
        if len(data) < 12:
            # There isn't enough data to calculate Bollinger Bands
            # log("Not enough data to calculate Bollinger Bands")
            return TargetAllocation({})

        gcusd_stake = holdings.get("gcusd", 0)
        gcusd_bbands = BB("gcusd", data, 12, 1.5)
        current_price = data[-1]["gcusd"]['close']  # Current price of gcusd

        # log(f" {current_price}  {gcusd_bbands['lower'][-1]}   {gcusd_bbands['mid'][-1]}")

        # Buying condition: the price falls below the lower Bollinger Band
        if gcusd_stake ==0 and current_price < gcusd_bbands['lower'][-1]:
            # log(f"Buying gcusd - price below lower Bollinger Band. Current price: {current_price}")
            gcusd_stake = 1  # Buy gcusd
        # Selling condition: the price moves above the middle Bollinger Band
        if gcusd_stake >0 and current_price > gcusd_bbands['mid'][-1]:
            # log(f"Closing gcusd - price above middle Bollinger Band. Current price: {current_price}")
            gcusd_stake = 0  # Exit position in gcusd

        return TargetAllocation({"gcusd": gcusd_stake})