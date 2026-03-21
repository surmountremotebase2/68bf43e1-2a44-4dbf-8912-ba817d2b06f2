from surmount.base_class import Strategy, TargetAllocation
from surmount.data import NDWPowerSmall

class TradingStrategy(Strategy):

    def __init__(self):
        self.data_list = [NDWPowerSmall()]
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

        for model in self.data_list:
            if tuple(model)[0] == "ndw_powersmall":
                ndw_data = data.get(tuple(model))

                if ndw_data and len(ndw_data) > 0:
                    allocations = ndw_data[-1].get("allocations", {})
                    total_weight = sum(allocations.values())

                    if total_weight > 0:
                        normalized = {k: v / total_weight for k, v in allocations.items()}
                        return TargetAllocation(normalized)