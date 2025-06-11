from surmount.base_class import Strategy, TargetAllocation
from surmount.data import TopGovernmentContracts, TopLobbyingContracts
from surmount.logging import log

class TradingStrategy(Strategy):

    def __init__(self):
        self.data_list = [TopGovernmentContracts(), TopLobbyingContracts()]
        self.contract_cache = {}  # Remember price at award date
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
        gov_contracts = data.get(("top_government_contracts",), [])
        lobbying_data = data.get(("top_lobbying_contracts",), [])
        ohlcv_data = data.get("ohlcv", [])

        if not ohlcv_data:
            return TargetAllocation({})

        current_prices = ohlcv_data[-1]
        lobbying_spend = {}
        total_lobbying = 0
        contract_awards = set()

        # Parse lobbying data
        for entry in lobbying_data:
            ticker = entry["ticker"]
            amount = entry["amount"]
            lobbying_spend[ticker] = amount
            total_lobbying += amount

        # Track awarded contracts and award prices
        for contract in gov_contracts:
            ticker = contract["ticker"]
            if ticker not in current_prices:
                continue  # Ignore if no price data
            price = current_prices[ticker]["close"]
            contract_awards.add(ticker)
            if ticker not in self.contract_cache:
                self.contract_cache[ticker] = {
                    "award_price": price,
                    "award_date": current_prices[ticker]["date"]
                }

        # Update tickers list
        self.tickers = list(set(lobbying_spend.keys()).union(contract_awards))
        log(self.tickers)
        raw_scores = {}
        total_score = 0

        for ticker in self.tickers:
            if ticker not in current_prices:
                continue  # Don't allocate if we don't have OHLCV data

            score = 0
            if ticker in contract_awards:
                score += 0.5

            if ticker in lobbying_spend and total_lobbying > 0:
                lobbying_weight = lobbying_spend[ticker] / total_lobbying
                score += 0.5 * lobbying_weight

            # Profit-taking check
            if ticker in self.contract_cache:
                award_price = self.contract_cache[ticker]["award_price"]
                current_price = current_prices[ticker]["close"]
                change = (current_price - award_price) / award_price
                if change >= 0.5:
                    log(f"Trimming {ticker} - profit exceeded 50% since contract award")
                    continue  # Skip allocating

            raw_scores[ticker] = score
            total_score += score

        # Normalize allocation
        if total_score > 0:
            for ticker, score in raw_scores.items():
                allocation_dict[ticker] = score / total_score

        return TargetAllocation(allocation_dict)