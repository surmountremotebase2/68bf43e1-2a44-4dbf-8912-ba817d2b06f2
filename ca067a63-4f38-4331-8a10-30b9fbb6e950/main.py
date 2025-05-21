from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        self.tickers = ["GLD", "XOM", "COP", "ET", "BAM", "PLD"]
        self.data_list = [MedianCPI()]
        self.count = 0

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
        allocation = {ticker: 0 for ticker in self.tickers}
        weights = {ticker: 1 for ticker in self.tickers}
        ohlcv = data["ohlcv"]

        # Get CPI value from proper data source
        median_cpi_data = data[("median_cpi",)]
        if not median_cpi_data or len(median_cpi_data) < 1:
            log("Missing CPI data, fallback to equal weight.")
            equal_weight = 1 / len(self.tickers)
            return TargetAllocation({ticker: equal_weight for ticker in self.tickers})

        latest_cpi = median_cpi_data[-1]["value"]
        high_inflation = latest_cpi > 5
        log(f"Latest CPI: {latest_cpi} | High Inflation: {high_inflation}")

        for ticker in self.tickers:
            # Extract recent close prices
            close_prices = [bar[ticker]["close"] for bar in ohlcv if ticker in bar]
            if len(close_prices) < 60:
                log(f"Not enough price data for {ticker}")
                continue

            current = close_prices[-1]
            month_ago = close_prices[-20]
            quarter_ago = close_prices[-60]

            month_change = (current - month_ago) / month_ago
            quarter_change = (current - quarter_ago) / quarter_ago

            log(f"{ticker} | Month: {month_change:.2%} | Quarter: {quarter_change:.2%}")

            # Profit-taking rule for GLD
            if ticker == "GLD" and quarter_change > 0.15:
                weights[ticker] *= 0.5

            # Stop-loss rule for oil assets
            if ticker in ["XOM", "COP", "ET"] and month_change < -0.10:
                weights[ticker] *= 0.5

            # Inflation hedge
            if high_inflation and ticker in ["GLD", "XOM"]:
                weights[ticker] *= 1.5

        total_weight = sum(weights.values())
        if total_weight == 0:
            return TargetAllocation({ticker: 0 for ticker in self.tickers})

        for ticker in self.tickers:
            allocation[ticker] = weights[ticker] / total_weight

        return TargetAllocation(allocation)