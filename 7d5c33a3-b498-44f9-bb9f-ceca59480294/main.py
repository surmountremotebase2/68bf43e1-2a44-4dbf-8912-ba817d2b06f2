from surmount.base_class import Strategy, TargetAllocation
from surmount.data import Asset, AnalystRatings, Fundamentals
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = ["AAPL", "FB", "AMZN", "NFLX", "GOOGL"]  # Example tech stocks
        self.data_list = [Fundamentals(i) for i in self.tickers]
        self.data_list += [AnalystRatings(i) for i in self.tickers]

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
        allocations = {}
        pbr_dict = {}  # Price-to-Book Ratio dictionary
        downgrade_dict = {}  # Analyst Downgrades dictionary
        
        # Fetch the fundamentals and analyst ratings for each ticker
        for i in self.tickers:
            fundamentals = data.get(('fundamentals', i), None)
            ratings = data.get(('analyst_ratings', i), None)

            if fundamentals:
                pbr = fundamentals['priceToBook']
                pbr_dict[i] = pbr
            
            if ratings:
                # Count downgrades in the latest analyst ratings
                downgrades = sum(1 for rating in ratings if rating['action'] == 'downgrade')
                downgrade_dict[i] = downgrades

        # Normalize and invert PBR scores (lower PBR indicates undervaluation)
        min_pbr, max_pbr = min(pbr_dict.values()), max(pbr_dict.values())
        for i in pbr_dict:
            pbr_dict[i] = (max_pbr - pbr_dict[i]) / (max_pbr - min_pbr if max_pbr - min_pbr else 1)

        # Normalize downgrade scores (more downgrades indicate overvaluation)
        max_downgrades = max(downgrade_dict.values()) if downgrade_dict.values() else 0
        for i in downgrade_dict:
            downgrade_dict[i] = downgrade_memes[i] / max_downgrades if max_downgrades else 0

        # Combine PBR and downgrade scores for a final valuation score (higher score indicates undervaluation)
        for i in self.tickers:
            pbr_score = pbr_dict.get(i, 0) * 0.5 # Weight can be adjusted
            downgrade_score = downgrade_dict.get(i, 0) * 0.5 # Weight can be adjusted
            final_score = pbr_score + downgrade_score
            
            # Here we decide on a strategy to short overvalued and buy undervalued stocks based on the final_score
            # This example simply splits allocation equally among stocks considered as undervalued (final_score > threshold)
            if final_score > 0.5:  # Threshold can be adjusted
                allocations[i] = 1 / len(self.tickers)  # Equally weighted for simplicity
            else:
                allocations[i] = 0  # Do not allocate to overvalued stocks

        return TargetAllocation(allocations)