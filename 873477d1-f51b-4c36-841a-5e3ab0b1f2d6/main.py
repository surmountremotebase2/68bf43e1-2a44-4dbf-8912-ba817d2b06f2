from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.data import MedianCPI
import math


class TradingStrategy(Strategy):

    def __init__(self):

        self.tickers = [
            "CWB",
            "HYG",
            "TLT",
            "IEF",
            "TIP",
            "SHY",
            "SPY",
            "GLD"
        ]

        self.data_list = [
            MedianCPI()
        ]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return self.data_list

    # ============================================================
    # Helpers
    # ============================================================

    def get_close_series(self, ohlcv, ticker):

        closes = []

        for bar in ohlcv:

            if (
                ticker in bar
                and bar[ticker]
                and "close" in bar[ticker]
                and bar[ticker]["close"] is not None
            ):
                closes.append(bar[ticker]["close"])

        return closes

    def sma(self, values, length):

        if len(values) < length:
            return None

        return sum(values[-length:]) / length

    def monthly_series(self, values):
        """
        Approximate monthly closes using 21 trading days.
        """

        if len(values) < 21:
            return []

        monthly = []

        for i in range(20, len(values), 21):
            monthly.append(values[i])

        return monthly

    def momentum_return(self, values, months=6):

        lookback = months * 21

        if len(values) < lookback + 1:
            return None

        current = values[-1]
        past = values[-lookback]

        if past == 0:
            return None

        return (current / past) - 1

    def annualized_volatility(self, values, lookback=20):

        if len(values) < lookback + 1:
            return None

        returns = []

        for i in range(-lookback, 0):

            prev_close = values[i - 1]
            curr_close = values[i]

            if prev_close == 0:
                continue

            ret = (curr_close / prev_close) - 1
            returns.append(ret)

        if len(returns) < 2:
            return None

        mean_ret = sum(returns) / len(returns)

        variance = sum(
            (r - mean_ret) ** 2 for r in returns
        ) / (len(returns) - 1)

        daily_vol = math.sqrt(variance)

        return daily_vol * math.sqrt(252)

    # ============================================================
    # Main Logic
    # ============================================================

    def run(self, data):

        allocations = {
            ticker: 0.0 for ticker in self.tickers
        }

        ohlcv = data["ohlcv"]

        # ========================================================
        # Load Price History
        # ========================================================

        prices = {}

        required_min_bars = 160

        for ticker in self.tickers:

            closes = self.get_close_series(
                ohlcv,
                ticker
            )

            # ----------------------------------------------------
            # FIX:
            # Some ETFs start later in backtests.
            # Do NOT stop strategy execution.
            # ----------------------------------------------------

            if len(closes) < required_min_bars:

                log(
                    f"Skipping {ticker}: "
                    f"only {len(closes)} bars"
                )

                prices[ticker] = None

            else:
                prices[ticker] = closes

        # ========================================================
        # Critical Assets Check
        # ========================================================

        critical_assets = [
            "SPY",
            "GLD",
            "HYG",
            "IEF",
            "SHY"
        ]

        for asset in critical_assets:

            if prices[asset] is None:

                log(
                    f"Critical asset missing: {asset}"
                )

                return TargetAllocation(allocations)

        # ========================================================
        # Monthly Macro Regime
        # ========================================================

        spy_monthly = self.monthly_series(
            prices["SPY"]
        )

        gld_monthly = self.monthly_series(
            prices["GLD"]
        )

        if (
            len(spy_monthly) < 12
            or len(gld_monthly) < 12
        ):
            return TargetAllocation(allocations)

        ratio_series = []

        for i in range(len(spy_monthly)):

            if gld_monthly[i] == 0:
                ratio_series.append(0)
            else:
                ratio_series.append(
                    spy_monthly[i] / gld_monthly[i]
                )

        ratio_sma_12 = self.sma(
            ratio_series,
            12
        )

        if ratio_sma_12 is None:
            return TargetAllocation(allocations)

        current_ratio = ratio_series[-1]

        risk_on_macro = (
            current_ratio > ratio_sma_12
        )

        # ========================================================
        # SPY Trend
        # ========================================================

        spy_sma_10 = self.sma(
            spy_monthly,
            10
        )

        if spy_sma_10 is None:
            return TargetAllocation(allocations)

        spy_trend = (
            spy_monthly[-1] > spy_sma_10
        )

        risk_on = (
            risk_on_macro
            and spy_trend
        )

        # ========================================================
        # Trend Filters
        # ========================================================

        def trend_filter(ticker):

            if prices[ticker] is None:
                return False

            monthly_prices = self.monthly_series(
                prices[ticker]
            )

            if len(monthly_prices) < 10:
                return False

            sma_10 = self.sma(
                monthly_prices,
                10
            )

            if sma_10 is None:
                return False

            return (
                monthly_prices[-1] > sma_10
            )

        cwb_trend = trend_filter("CWB")
        tlt_trend = trend_filter("TLT")

        # ========================================================
        # Relative Strength
        # ========================================================

        momentum = {}

        rotation_assets = [
            "CWB",
            "HYG",
            "TLT",
            "IEF",
            "TIP",
            "SHY"
        ]

        for ticker in rotation_assets:

            if prices[ticker] is None:
                momentum[ticker] = None
            else:
                momentum[ticker] = self.momentum_return(
                    prices[ticker],
                    months=6
                )

        # ========================================================
        # CPI Regime
        # ========================================================

        median_cpi_data = data.get(
            ("median_cpi",)
        )

        if (
            not median_cpi_data
            or len(median_cpi_data) < 1
        ):

            inflation_value = 2.5

        else:

            inflation_value = (
                median_cpi_data[-1]["value"]
            )

        inflationary_regime = (
            inflation_value > 3.5
        )

        # ========================================================
        # Asset Selection
        # ========================================================

        selected_asset = None

        # --------------------------------------------------------
        # Risk-On
        # --------------------------------------------------------

        if risk_on:

            cwb_mom = momentum["CWB"]
            hyg_mom = momentum["HYG"]

            # If CWB unavailable -> fallback to HYG
            if (
                cwb_mom is not None
                and hyg_mom is not None
                and cwb_mom > hyg_mom
                and cwb_trend
            ):

                selected_asset = "CWB"

            else:

                selected_asset = "HYG"

        # --------------------------------------------------------
        # Risk-Off
        # --------------------------------------------------------

        else:

            # Inflationary
            if inflationary_regime:

                tip_mom = momentum["TIP"]
                shy_mom = momentum["SHY"]

                if (
                    tip_mom is not None
                    and shy_mom is not None
                    and tip_mom > shy_mom
                ):

                    selected_asset = "TIP"

                else:

                    selected_asset = "SHY"

            # Disinflationary
            else:

                tlt_mom = momentum["TLT"]
                ief_mom = momentum["IEF"]

                if (
                    tlt_mom is not None
                    and ief_mom is not None
                    and tlt_mom > ief_mom
                    and tlt_trend
                ):

                    selected_asset = "TLT"

                else:

                    selected_asset = "IEF"

        # ========================================================
        # Volatility Targeting
        # ========================================================

        if (
            selected_asset is None
            or prices[selected_asset] is None
        ):
            return TargetAllocation(allocations)

        target_vol = 0.10

        realized_vol = self.annualized_volatility(
            prices[selected_asset],
            lookback=20
        )

        if (
            realized_vol is None
            or realized_vol <= 0
        ):

            exposure = 1.0

        else:

            exposure = (
                target_vol / realized_vol
            )

        exposure = max(
            0.0,
            min(1.0, exposure)
        )

        # ========================================================
        # Final Allocation
        # ========================================================

        allocations[selected_asset] = exposure

        log(
            f"Selected={selected_asset} | "
            f"RiskOn={risk_on} | "
            f"CPI={round(inflation_value, 2)} | "
            f"Exposure={round(exposure, 3)}"
        )

        return TargetAllocation(allocations)