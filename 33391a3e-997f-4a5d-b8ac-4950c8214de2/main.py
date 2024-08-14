from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime

class TradingStrategy(Strategy):

    def __init__(self):
        self.tickers = [
            "LMT", "NOC", "BA", "MAXR", "RTX", "AJRD", "LHX", "OIG", "SPCE", "AVAV"
        ]
        self.weights = [
            0.15, 0.10, 0.10, 0.10, 0.12, 0.11, 0.10, 0.02, 0.10, 0.09
        ]

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers

    def run(self, data):
        today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
        yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')
        
        if today.day == 10 or (today.day > 10 and yesterday.day < 10):
            # Normalize the weights to add up to 1
            total_weight = sum(self.weights)
            allocation_dict = {self.tickers[i]: self.weights[i]/total_weight for i in range(len(self.tickers))}
            return TargetAllocation(allocation_dict)
        return None