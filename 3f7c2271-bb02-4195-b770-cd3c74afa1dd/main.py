import math

from surmount.base_class import Strategy, TargetAllocation


class TradingStrategy(Strategy):
    """
    Monthly Relative Strength Rotation with 200-day SMA Filter

    Method:
        - Daily data (1day).
        - Rebalance every 21 trading sessions.
        - Rank ETFs by trailing 175-session return.
        - Select the top 3 ETFs.
        - Exclude selected ETFs trading below their 200-day SMA.
        - Equally weight the remaining eligible ETFs.
        - Maintain allocations between rebalances.
    """

    def __init__(self):
        self.tickers = [
            "SPY", "RSP", "QQQ", "XLV", "XLF", "FEZ", "VXUS", "VPL", "GLD",
            "DBC", "IJT", "IEF", "TLT", "BND", "SHY", "AGG"
        ]

        self.lookback = 175
        self.sma_period = 100
        self.top_n = 3
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

        # Require sufficient history for both momentum and SMA.
        required_history = max(
            self.lookback + 1,
            self.sma_period
        )

        if current_index < required_history - 1:
            return TargetAllocation({})

        # Most recent scheduled rebalance point.
        rebalance_index = (
            current_index -
            (current_index % self.rebalance_period)
        )

        momentum_start_index = (
            rebalance_index - self.lookback
        )

        sma_start_index = (
            rebalance_index - self.sma_period + 1
        )

        if momentum_start_index < 0 or sma_start_index < 0:
            return TargetAllocation({})

        performance = {}
        above_sma = {}

        for ticker in self.tickers:

            try:
                start_close = float(
                    ohlcv[momentum_start_index][ticker]["close"]
                )

                current_close = float(
                    ohlcv[rebalance_index][ticker]["close"]
                )

                sma_closes = [
                    float(ohlcv[i][ticker]["close"])
                    for i in range(
                        sma_start_index,
                        rebalance_index + 1
                    )
                ]

                if (
                    not math.isfinite(start_close)
                    or not math.isfinite(current_close)
                    or start_close <= 0
                    or current_close <= 0
                    or len(sma_closes) != self.sma_period
                    or not all(math.isfinite(p) and p > 0
                               for p in sma_closes)
                ):
                    continue

                # Trailing 175-session momentum.
                performance[ticker] = (
                    current_close / start_close
                ) - 1.0

                # 200-day simple moving average.
                sma_200 = sum(sma_closes) / self.sma_period

                above_sma[ticker] = current_close >= sma_200

            except (KeyError, IndexError, TypeError, ValueError):
                continue

        # Need valid momentum and SMA data.
        if not performance:
            return TargetAllocation({})

        # Rank the entire available universe by momentum.
        ranked_etfs = sorted(
            performance.keys(),
            key=lambda ticker: performance[ticker],
            reverse=True
        )

        # Select the top 3 before applying the trend filter.
        top_candidates = ranked_etfs[:self.top_n]

        # Exclude ETFs below their 200-day SMA.
        eligible_etfs = [
            ticker
            for ticker in top_candidates
            if above_sma.get(ticker, False)
        ]

        # Default to zero allocation for every ETF.
        allocation = {
            ticker: 0.0
            for ticker in self.tickers
        }

        # Equal-weight the surviving ETFs.
        if eligible_etfs:
            weight = 1.0 / len(eligible_etfs)

            for ticker in eligible_etfs:
                allocation[ticker] = weight

        return TargetAllocation(allocation)