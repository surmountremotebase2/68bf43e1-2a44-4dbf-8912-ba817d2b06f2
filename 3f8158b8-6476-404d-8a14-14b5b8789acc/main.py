from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = [
            "PLD", "SPG", "EQIX", "VNO", "PSA", "WELL", "BXP", "VTR", "AVB",
            "AMT", "ARE", "O", "DLR", "WY", "CCI", "HST", "MGM", "HLT", "KIM",
            "SBAC", "IRM", "MPW", "EXR", "ESS", "UDR", "GLPI",
            "JRS"
        ]
        self.weights = [
            0.05, 0.04, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03, 0.02,
            0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02,
            0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01,
        ]

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers

    def run(self, data):
        if len(data) > 0:
            today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
            yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')
            
            if today.day == 8 or (today.day > 8 and yesterday.day < 8):
                # Normalize the weights to add up to 1
                total_weight = sum(self.weights)
                allocation_dict = {self.tickers[i]: self.weights[i]/total_weight for i in range(len(self.tickers))}
                return TargetAllocation(allocation_dict)
        return None