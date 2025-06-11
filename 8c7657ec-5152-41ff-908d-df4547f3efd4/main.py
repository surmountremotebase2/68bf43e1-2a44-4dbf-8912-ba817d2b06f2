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
            log("No OHLCV data — fallback to equal allocation.")
            fallback_tickers = list({entry["ticker"] for entry in lobbying_data + gov_contracts})
            weight = 1.0 / len(fallback_tickers) if fallback_tickers else 0
            return TargetAllocation({t: weight for t in fallback_tickers})

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
            if ticker in current_prices:
                contract_awards.add(ticker)
                if ticker not in self.contract_cache:
                    self.contract_cache[ticker] = {
                        "award_price": current_prices[ticker]["close"],
                        "award_date": current_prices[ticker]["date"]
                    }

        self.tickers = list(set(lobbying_spend.keys()).union(contract_awards))
        raw_scores = {}
        total_score = 0

        for ticker in self.tickers:
            if ticker not in current_prices:
                log(f"Missing price for {ticker}, skipping.")
                continue

            score = 0.5 if ticker in contract_awards else 0
            if ticker in lobbying_spend and total_lobbying > 0:
                score += 0.5 * lobbying_spend[ticker] / total_lobbying

            if ticker in self.contract_cache:
                award_price = self.contract_cache[ticker]["award_price"]
                current_price = current_prices[ticker]["close"]
                price_change = (current_price - award_price) / award_price
                if price_change >= 0.5:
                    log(f"{ticker} up {price_change*100:.1f}% — skipping due to profit rule.")
                    continue

            raw_scores[ticker] = score
            total_score += score

        if total_score > 0:
            for ticker, score in raw_scores.items():
                allocation_dict[ticker] = score / total_score
        else:
            # No valid tickers with prices — fallback to equal allocation
            fallback_tickers = list(set(lobbying_spend.keys()).union(contract_awards))
            log("All tickers filtered out or missing prices — fallback to equal allocation.")
            weight = 1.0 / len(fallback_tickers) if fallback_tickers else 0
            allocation_dict = {t: weight for t in fallback_tickers}

        return TargetAllocation(allocation_dict)
