import math
from datetime import datetime

from surmount.base_class import Strategy, TargetAllocation


class TradingStrategy(Strategy):
    """
    Monthly Relative Strength Rotation

    Universe:
        SPY - US Equities
        EEM - Emerging Markets Equities
        TLT - US Long-Term Treasury Bonds

    Strategy:
        - Uses daily OHLCV data.
        - Identifies the latest completed calendar month.
        - Calculates each ETF's return over that calendar month.
        - Allocates 100% to the ETF with the highest return.
        - Holds the selected ETF until the next monthly rebalance.

    Rebalancing:
        Monthly.

    Allocation:
        Long-only, fully invested, no leverage.
    """

    def __init__(self):
        self.tickers = ["SPY", "EEM", "TLT"]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Supported interval used by the Surmount backtester.
        return "1day"

    @property
    def data(self):
        return []

    @staticmethod
    def _parse_date(value):
        """
        Convert a daily OHLCV date into a datetime object.

        Supports common date representations:
        YYYY-MM-DD
        YYYY-MM-DD HH:MM:SS
        ISO-8601 timestamps.
        """
        if isinstance(value, datetime):
            return value

        if not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

        for date_format in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(value, date_format)
            except ValueError:
                continue

        return None

    @staticmethod
    def _valid_price(value):
        try:
            price = float(value)
            return math.isfinite(price) and price > 0
        except (TypeError, ValueError):
            return False

    def run(self, data):

        ohlcv = data.get("ohlcv", [])

        if not ohlcv:
            return TargetAllocation({})

        # Build a chronological collection of daily observations.
        observations = []

        for record in ohlcv:

            if not isinstance(record, dict):
                continue

            date = TradingStrategy._parse_date(
                record.get("date")
            )

            if date is None:
                continue

            observations.append((date, record))

        if not observations:
            return TargetAllocation({})

        observations.sort(key=lambda item: item[0])

        # The latest available observation determines the
        # current month represented in the historical data.
        latest_date = observations[-1][0]

        # We only calculate a signal for a completed month.
        # If the latest data is still inside a month, use the
        # previous calendar month.
        #
        # At a month-end backtest execution, the latest daily
        # candle should represent the completed month.
        if latest_date.month == 12:
            next_month = datetime(
                latest_date.year + 1, 1, 1,
                tzinfo=latest_date.tzinfo
            )
        else:
            next_month = datetime(
                latest_date.year,
                latest_date.month + 1,
                1,
                tzinfo=latest_date.tzinfo
            )

        # Identify the latest completed calendar month.
        if latest_date < next_month:
            # If the last available daily candle is not the
            # final trading session of its calendar month,
            # do not treat that month as completed.
            current_month = latest_date.month
            current_year = latest_date.year

            month_observations = [
                (date, record)
                for date, record in observations
                if date.year == current_year
                and date.month == current_month
            ]

            # Check whether the latest available observation
            # belongs to the current calendar month.
            # A month is considered complete only when the
            # backtest data has advanced into the next month.
            #
            # This avoids using partial-month returns.
            completed_month_observations = [
                (date, record)
                for date, record in observations
                if (
                    date.year < current_year
                    or (
                        date.year == current_year
                        and date.month < current_month
                    )
                )
            ]

            if not completed_month_observations:
                return TargetAllocation({})

            latest_completed_date = completed_month_observations[-1][0]

        else:
            latest_completed_date = latest_date

        signal_year = latest_completed_date.year
        signal_month = latest_completed_date.month

        # Identify the preceding calendar month.
        if signal_month == 1:
            previous_year = signal_year - 1
            previous_month = 12
        else:
            previous_year = signal_year
            previous_month = signal_month - 1

        # Collect the daily observations for both months.
        current_month_data = [
            (date, record)
            for date, record in observations
            if date.year == signal_year
            and date.month == signal_month
        ]

        previous_month_data = [
            (date, record)
            for date, record in observations
            if date.year == previous_year
            and date.month == previous_month
        ]

        if not current_month_data or not previous_month_data:
            return TargetAllocation({})

        # Use the final available trading-day close for each month.
        previous_month_close_record = previous_month_data[-1][1]
        current_month_close_record = current_month_data[-1][1]

        performance = {}

        for ticker in self.tickers:

            try:
                previous_price = previous_month_close_record[
                    ticker
                ]["close"]

                current_price = current_month_close_record[
                    ticker
                ]["close"]

                if not (
                    TradingStrategy._valid_price(previous_price)
                    and TradingStrategy._valid_price(current_price)
                ):
                    continue

                previous_price = float(previous_price)
                current_price = float(current_price)

                monthly_return = (
                    current_price / previous_price
                ) - 1.0

                performance[ticker] = monthly_return

            except (KeyError, TypeError, ValueError):
                continue

        # Require valid prices for all three ETFs.
        if len(performance) != len(self.tickers):
            return TargetAllocation({})

        # Select the ETF with the highest monthly return.
        # Ticker order provides deterministic tie-breaking.
        best_performer = max(
            self.tickers,
            key=lambda ticker: performance[ticker]
        )

        allocation = {
            ticker: 1.0 if ticker == best_performer else 0.0
            for ticker in self.tickers
        }

        return TargetAllocation(allocation)