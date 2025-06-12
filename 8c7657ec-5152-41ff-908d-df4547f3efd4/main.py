from surmount.base_class import Strategy, TargetAllocation
from surmount.data import TopGovernmentContracts, TopLobbyingContracts
from surmount.technical_indicators import STDEV
from surmount.logging import log

class TradingStrategy(Strategy):

    def __init__(self):
        self.data_list = [TopGovernmentContracts(), TopLobbyingContracts()]
        self.tickers = [
            "MSFT", "NVDA", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "BRK.B", "TSLA", "TSM",
            "WMT", "JPM", "LLY", "V", "MA", "NFLX", "ORCL", "XOM", "COST", "PG",
            "JNJ", "HD", "NVO", "SAP", "ABBV", "BAC", "PLTR", "ASML", "KO", "PM",
            "UNH", "BABA", "TMUS", "GE", "IBM", "CRM", "CSCO", "CVX", "WFC", "TM",
            "ABT", "NVS", "AZN", "LIN", "MCD", "DIS", "INTU", "MS", "AXP", "NOW",
            "PEP", "PFE", "AMD", "ADBE", "TXN", "INTC", "UNP", "LMT", "UPS", "BP",
            "SCHW", "RTX", "GS", "BLK", "CAT", "HON", "SBUX", "MDT", "PYPL", "BKNG",
            "BK", "EL", "DHR", "TGT", "BA", "VZ", "CMCSA", "GSK", "SNY", "MO",
            "TJX", "CI", "BMY", "LOW", "F", "SPGI", "MMM", "MDLZ", "DE", "COP",
            "GILD", "AON", "BDX", "ISRG", "RIO", "NEE", "CSX", "PGR", "AMT", "HCA"
        ]

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
        ohlcv = data["ohlcv"]
        gov_contracts = data[("top_government_contracts",)]
        lobbying_data = data[("top_lobbying_contracts",)]

        allocation = {ticker: 0 for ticker in self.tickers}

        if len(ohlcv) < 126:
            log("Not enough OHLCV data — fallback to equal allocation.")
            weight = 1.0 / len(self.tickers)
            return TargetAllocation({ticker: weight for ticker in self.tickers})

        # Build lookup for contract and lobbying
        contract_awarded = set()
        lobbying_spend = {}
        total_lobbying = 0

        for entry in gov_contracts:
            t = entry["ticker"]
            if t in self.tickers:
                contract_awarded.add(t)

        for entry in lobbying_data:
            t = entry["ticker"]
            if t in self.tickers:
                lobbying_spend[t] = entry["amount"]
                total_lobbying += entry["amount"]

        # Score and filter
        raw_scores = {}
        total_score = 0

        for ticker in self.tickers:
            try:
                close_prices = [day[ticker]["close"] for day in ohlcv[-126:] if ticker in day]
                if len(close_prices) < 126:
                    continue

                returns = (close_prices[-1] / close_prices[0]) - 1
                volatility = STDEV(ticker, ohlcv, 126)
                vol = volatility[-1] if volatility else 1

                # Profit-taking rule
                if returns >= 0.5:
                    log(f"{ticker} return {returns:.2%} — skipping (profit rule)")
                    continue

                score = 0.0
                if ticker in contract_awarded:
                    score += 0.5
                if ticker in lobbying_spend and total_lobbying > 0:
                    score += 0.5 * lobbying_spend[ticker] / total_lobbying

                raw_scores[ticker] = score
                total_score += score
            except:
                continue  # Skip tickers with missing or invalid data

        if total_score > 0:
            for ticker, score in raw_scores.items():
                allocation[ticker] = score / total_score
        else:
            log("All tickers filtered — fallback to equal weights.")
            fallback = [t for t in self.tickers if t in raw_scores]
            weight = 1.0 / len(fallback) if fallback else 0
            allocation = {t: weight for t in fallback}

        return TargetAllocation(allocation)