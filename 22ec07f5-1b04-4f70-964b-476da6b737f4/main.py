from surmount.base_class import Strategy, TargetAllocation
from surmount.data import CoinbaseCryptoAltRanking
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        self.data_list = [CoinbaseCryptoAltRanking()]
        self.tickers = []
        self.counter = 0

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
        # Increment the internal day counter
        self.counter += 1

        # Only rebalance every 30 days
        if self.counter % 30 != 1:
            return TargetAllocation({})

        crypto_rankings = data[("coinbase_crypto_alt_ranking",)]
        crypto_rankings = [x for x in crypto_rankings[-40:] if x]
        #log(f"rankings {crypto_rankings[:10]}")

        if len(crypto_rankings) < 5:
            return TargetAllocation({})

        # Prepare AltRank history
        alt_rank_history = {}
        for day_data in crypto_rankings:
            for coin, rank in day_data["alt_ranking"].items():
                if coin != "RENDER":
                    if coin not in alt_rank_history:
                        alt_rank_history[coin] = []
                    alt_rank_history[coin].append(rank)

        # Compute average AltRank
        average_ranks = []
        for coin, ranks in alt_rank_history.items():
            if len(ranks) == 40:
                avg_rank = sum(ranks) / len(ranks)
                average_ranks.append((coin, avg_rank))

        # Select top 20 coins by average AltRank
        top_20 = sorted(average_ranks, key=lambda x: x[1])[:15]
        log(f"rankings {top_20[:10]}")

        allocation = {}
        #self.tickers = []

        for coin, _ in top_20:
            symbol = coin + "USD"
            allocation[symbol] = 1 / len(top_20)
            #self.tickers.append(symbol)

        return TargetAllocation(allocation)