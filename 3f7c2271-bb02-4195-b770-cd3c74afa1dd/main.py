import math

from surmount.base_class import Strategy, TargetAllocation


class TradingStrategy(Strategy):
    """
    Monthly Relative Strength Rotation

    Universe:
        SPY - US Equities
        EEM - Emerging Markets Equities
        TLT - Long-Term US Treasury Bonds

    Method:
        - Uses daily OHLCV data.
        - Calculates trailing 21-trading-session performance.
        - Selects the ETF with the highest return.
        - Holds the selected ETF for approximately one month.
        - Re-evaluates after each 21-session holding period.

    No timestamp field is required.
    """

    def __init__(self):
        self.tickers = ["SPY", "EEM", "TLT"]
        self.lookback = 21
        self.rebalance_period = 21

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []

    def run(self, data):

        ohlcv = data.get("ohlcv", [])

        # Require sufficient observations for the lookback
        # and a valid previous observation.
        if len(ohlcv) < 1:
            return TargetAllocation({})

        # Determine the current position in the trading-session
        # sequence. Rebalance once every 21 observations.
        current_index = len(ohlcv) - 1

        if current_index % self.rebalance_period != 0:
            return TargetAllocation({})

        performance = {}

        # Calculate trailing 21-session returns.
        for ticker in self.tickers:
            try:
                current_close = float(
                    ohlcv[-1][ticker]["close"]
                )

                previous_close = float(
                    ohlcv[-(self.lookback + 1)][ticker]["close"]
                )

                if (
                    not math.isfinite(current_close)
                    or not math.isfinite(previous_close)
                    or current_close <= 0
                    or previous_close <= 0
                ):
                    continue

                performance[ticker] = (
                    current_close / previous_close
                ) - 1.0

            except (KeyError, TypeError, ValueError):
                continue

        # Avoid making a decision with incomplete universe data.
        if len(performance) != len(self.tickers):
            return TargetAllocation({})

        # Select the strongest ETF.
        best_performer = max(
            self.tickers,
            key=lambda ticker: performance[ticker]
        )

        # Allocate 100% to the winner.
        allocation = {
            ticker: (
                1.0 if ticker == best_performer else 0.0
            )
            for ticker in self.tickers
        }

        return TargetAllocation(allocation)