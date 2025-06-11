from surmount.base_class import Strategy, TargetAllocation
from surmount.data import TopGovernmentContracts, TopLobbyingContracts
from surmount.logging import log

class TradingStrategy(Strategy):

    def __init__(self):
        self.data_list = [TopGovernmentContracts(), TopLobbyingContracts()]
        self.contract_cache = {}
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
            log("No OHLCV data available.")
            return TargetAllocation({})

        current_prices = ohlcv_data[-1]
        lobbying_spend = {}
        total_lobbying = 0
        contract_awards = set()

        for entry in lobbying_data:
            ticker = entry["ticker"]
            amount = entry["amount"]
            lobbying_spend[ticker] = amount
            total_lobbying += amount

        for contract in gov_contracts:
            ticker = contract["ticker"]
            if ticker not in current_prices:
                log(f"Skipping {ticker} — no price data for contract award.")
                continue
            price = current_prices[ticker]["close"]
            contract_awards.add(ticker)
            if ticker not in self.contract_cache:
                self.contract_cache[ticker] = {
                    "award_price": price,
                    "award_date": current_prices[ticker]["date"]
                }

        self.tickers = list(set(lobbying_spend.keys()).union(contract_awards))
        raw_scores = {}
        total_score = 0

        for ticker in self.tickers:
            if ticker not in current_prices:
                log(f"Skipping {ticker} — no current price data.")
                continue

            score = 0
            if ticker in contract_awards:
                score += 0.5

            if ticker in lobbying_spend and total_lobbying > 0:
                lobbying_weight = lobbying_spend[ticker] / total_lobbying
                score += 0.5 * lobbying_weight

            # Check profit-taking condition
            if ticker in self.contract_cache:
                award_price = self.contract_cache[ticker]["award_price"]
                current_price = current_prices[ticker]["close"]
                change = (current_price - award_price) / award_price
                if change >= 0.5:
                    log(f"{ticker} up {change*100:.2f}% — profit taken.")
                    continue

            log(f"{ticker}: score = {score:.4f}")
            raw_scores[ticker] = score
            total_score += score

        if total_score > 0:
            for ticker, score in raw_scores.items():
                allocation = score / total_score
                log(f"Allocating {ticker}: {allocation:.4f}")
                allocation_dict[ticker] = allocation
        else:
            log("No valid allocations — total score is zero.")

        return TargetAllocation(allocation_dict)