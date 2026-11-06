import math

from surmount.base_class import Strategy, TargetAllocation


class TradingStrategy(Strategy):
    """
    Monthly Relative Strength Rotation

    Universe:
        SPY, EEM, TLT

    Method:
        - Daily data (1day).
        - Rebalance every 21 trading sessions.
        - Rank ETFs by their trailing 21-session return.
        - Allocate 100% to the strongest ETF.
        - Maintain the selected allocation between rebalances.

    No timestamp field required.
    """

    def __init__(self):
        self.tickers = ["SPY", "QQQ", "XLV", "XLF", "GLD", "DBC", "IJT", "IEF", "TLT"]
        self.lookback = 175
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

        current_index = len(ohlcv) - 1

        # Need enough history to calculate the first
        # 21-session return.
        if current_index < self.lookback:
            return TargetAllocation({})

        # Find the most recent scheduled rebalance index.
        rebalance_index = (
            current_index -
            (current_index % self.rebalance_period)
        )

        # Calculate momentum using prices available at
        # the most recent rebalance point.
        start_index = rebalance_index - self.lookback

        if start_index < 0:
            return TargetAllocation({})

        performance = {}

        for ticker in self.tickers:

            try:
                start_close = float(
                    ohlcv[start_index][ticker]["close"]
                )

                end_close = float(
                    ohlcv[rebalance_index][ticker]["close"]
                )

                if (
                    not math.isfinite(start_close)
                    or not math.isfinite(end_close)
                    or start_close <= 0
                    or end_close <= 0
                ):
                    continue

                performance[ticker] = (
                    end_close / start_close
                ) - 1.0

            except (KeyError, TypeError, ValueError):
                continue

        # Require valid prices for the entire universe.
        if len(performance) != len(self.tickers):
            return TargetAllocation({})

        # Determine the strongest ETF at the last rebalance.
        best_performer = max(
            self.tickers,
            key=lambda ticker: performance[ticker]
        )

        # IMPORTANT:
        # Return the same target allocation on every daily
        # execution until the next scheduled rebalance.
        allocation = {
            ticker: 1.0 if ticker == best_performer else 0.0
            for ticker in self.tickers
        }

        return TargetAllocation(allocation)