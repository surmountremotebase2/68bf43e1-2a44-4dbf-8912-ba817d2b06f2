from surmount.base_class import Strategy, TargetAllocation
from surmount.data import TopGovernmentContracts, TopLobbyingContracts, TopCongressTraders
from surmount.logging import log

class TradingStrategy(Strategy):

    def __init__(self):
        self.data_list = [TopGovernmentContracts(), TopLobbyingContracts()]
        self.contract_cache = {}  # For tracking contract award dates and price
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
        allocation_dict = {}
        gov_contracts = data[("top_government_contracts",)]
        lobbying_data = data[("top_lobbying_contracts",)]
        ohlcv_data = data["ohlcv"]

        lobbying_spend = {}
        contract_awards = set()

        # Parse current lobbying amounts
        total_lobbying = 0
        for entry in lobbying_data:
            ticker = entry["ticker"]
            amount = entry["amount"]
            lobbying_spend[ticker] = amount
            total_lobbying += amount

        # Identify contract-winning companies and track award prices
        for contract in gov_contracts:
            ticker = contract["ticker"]
            if ticker not in ohlcv_data[-1]:
                continue
            price = ohlcv_data[-1][ticker]["close"]
            contract_awards.add(ticker)
            if ticker not in self.contract_cache:
                self.contract_cache[ticker] = {
                    "award_price": price,
                    "award_date": ohlcv_data[-1][ticker]["date"]
                }

        self.tickers = list(set(lobbying_spend.keys()).union(contract_awards))

        # Calculate scores and apply lobbying weighting
        raw_scores = {}
        total_score = 0
        for ticker in self.tickers:
            score = 0

            # Contract Award Weight
            if ticker in contract_awards:
                score += 0.5

            # Lobbying Influence Weight (normalized lobbying)
            if ticker in lobbying_spend and total_lobbying > 0:
                lobbying_weight = lobbying_spend[ticker] / total_lobbying
                score += 0.5 * lobbying_weight

            # Check for profit-taking rule
            if ticker in self.contract_cache and ticker in ohlcv_data[-1]:
                award_price = self.contract_cache[ticker]["award_price"]
                current_price = ohlcv_data[-1][ticker]["close"]
                price_change = (current_price - award_price) / award_price
                if price_change >= 0.5:
                    log(f"Profit-taking on {ticker}: +{price_change*100:.1f}%")
                    continue  # Skip allocating further to take profits

            raw_scores[ticker] = score
            total_score += score

        # Normalize allocations
        if total_score > 0:
            for ticker, score in raw_scores.items():
                allocation_dict[ticker] = score / total_score

        return TargetAllocation(allocation_dict)