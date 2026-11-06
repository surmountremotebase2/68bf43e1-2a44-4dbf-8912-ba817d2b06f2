import math

from surmount.base_class import Strategy, TargetAllocation


class TradingStrategy(Strategy):
    """
    Monthly Relative Strength Rotation

    Universe:
        SPY - US Equities
        EEM - Emerging Markets Equities
        TLT - US Long-Term Treasury Bonds

    Strategy:
        1. Calculate each ETF's previous-month return.
        2. Rank the ETFs by monthly performance.
        3. Allocate 100% to the best-performing ETF.
        4. Repeat monthly, retaining the same ETF if it remains
           the strongest performer.

    Rebalancing:
        Monthly, using completed monthly candles only.
    """

    def __init__(self):
        self.tickers = ["SPY", "EEM", "TLT", "QQQ", "IEF", "BIL"]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1month"

    @property
    def data(self):
        return []

    def run(self, data):

        ohlcv = data.get("ohlcv", [])

        # At least two completed monthly candles are required
        # to calculate the previous month's return.
        if len(ohlcv) < 2:
            return TargetAllocation({})

        performance = {}

        for ticker in self.tickers:

            try:
                previous_close = float(
                    ohlcv[-2][ticker]["close"]
                )

                latest_close = float(
                    ohlcv[-1][ticker]["close"]
                )

                # Validate prices before calculating returns.
                if (
                    not math.isfinite(previous_close)
                    or not math.isfinite(latest_close)
                    or previous_close <= 0
                    or latest_close <= 0
                ):
                    continue

                # Previous month's close-to-close return.
                monthly_return = (
                    latest_close / previous_close
                ) - 1.0

                performance[ticker] = monthly_return

            except (KeyError, TypeError, ValueError):
                continue

        # Do not trade if complete data is unavailable
        # for any asset in the investment universe.
        if len(performance) != len(self.tickers):
            return TargetAllocation({})

        # Rank by monthly performance, highest first.
        # Ticker order provides deterministic tie-breaking.
        best_performer = max(
            self.tickers,
            key=lambda ticker: performance[ticker]
        )

        # Fully invested in the monthly relative-strength leader.
        allocation = {
            ticker: 1.0 if ticker == best_performer else 0.0
            for ticker in self.tickers
        }

        return TargetAllocation(allocation)