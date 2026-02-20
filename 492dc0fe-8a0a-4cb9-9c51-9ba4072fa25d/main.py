from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from surmount.data import NDWFirstTrustFocusFive

class TradingStrategy(Strategy):
    def __init__(self):
        self.data_list = [NDWFirstTrustFocusFive()]
        self.tickers = []

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        log(self.data_list)
        for i in self.data_list:
            log(i)
            if tuple(i)[0] == "ndw_ftrust5":
                ndw_data = data.get(tuple(i))
                if ndw_data and len(ndw_data) > 0:
                    allocations = ndw_data[-1].get("allocations", {})
                    total = sum(allocations.values())
                    log(allocations)
                    if total > 0:
                        return TargetAllocation({k: v / total for k, v in allocations.items()})