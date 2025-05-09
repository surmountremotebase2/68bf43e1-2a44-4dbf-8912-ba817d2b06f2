from surmount.base_class import Strategy, TargetAllocation
from datetime import datetime

class TradingStrategy(Strategy):

    def __init__(self):
        self.assets = ["QQQ"]
        self.interval = "1day"
        self.stop_loss_percentage = -0.06  # 6% stop loss

    @property
    def assets(self):
        return self.assets

    @property
    def interval(self):
        return self.interval

    @property
    def data(self):
        return []

    def run(self, data):
        # Initial allocation is nothing
        allocation_dict = {"QQQ": 0.0}  

        # Ensure there is enough data to consider
        if len(data["ohlcv"]) < 2:
            return TargetAllocation(allocation_dict)

        # Retrieve the last two days of trading data for QQQ
        last_day_data = data["ohlcv"][-1]["QQQ"]
        previous_day_data = data["ohlcv"][-2]["QQQ"]
        
        # Parse the last trading day date
        last_trading_day_date = datetime.strptime(last_day_data["date"], "%Y-%m-%d %H:%M:%S")

        # Calculate the percentage change between open and close
        percentage_change = (last_day_data["close"] - last_day_data["open"]) / last_day_data["open"]
        
        # Calculate stop loss condition
        stop_loss_triggered = (last_day_data["low"] / previous_day_data["close"] <= self.stop_loss_percentage)

        # Buying condition: It's Monday and the close is less than 1% up compared to the open
        if last_trading_day_date.weekday() == 0 and percentage_change <= 0.01:
            allocation_dict = {"QQQ": 1.0}

        # Selling condition: It's Thursday 1 hour before market close or stop loss is triggered
        elif last_trading_day_date.weekday() == 3 or stop_loss_triggered:
            allocation_dict = {"QQQ": 0.0}

        return TargetAllocation(allocation_dict)