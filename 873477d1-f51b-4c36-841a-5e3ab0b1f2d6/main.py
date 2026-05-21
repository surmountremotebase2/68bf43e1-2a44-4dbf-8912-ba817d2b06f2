from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.data import MedianCPI
import math


class TradingStrategy(Strategy):
    """
    FixedIncomeBeat500

    Tactical fixed income rotation strategy using:
    - Macro regime detection
    - Trend following
    - Relative strength rotation
    - Inflation filtering
    - Volatility targeting
    """

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
    # Helper Functions
    # ============================================================

    def get_close_series(self, ohlcv_data, ticker):
        closes = []

        for bar in ohlcv_data:
            if ticker in bar and "close" in bar[ticker]:
                closes.append(bar[ticker]["close"])

        return closes

    def sma(self, values, length):
        if len(values) < length:
            return None

        return sum(values[-length:]) / length

    def monthly_series(self, daily_values):
        """
        Approximate monthly closes using 21 trading days.
        """
        monthly = []

        for i in range(20, len(daily_values), 21):
            monthly.append(daily_values[i])

        return monthly

    def momentum_return(self, values, months=6):
        """
        6-month momentum approximation.
        """
        lookback = months * 21

        if len(values) < lookback + 1:
            return None

        current = values[-1]
        past = values[-lookback]

        if past == 0:
            return None

        return (current / past) - 1

    def annualized_volatility(self, values, lookback=20):
        """
        20-day annualized realized volatility.
        """

        if len(values) < lookback + 1:
            return None

        returns = []

        for i in range(-lookback, 0):
            prev_close = values[i - 1]
            curr_close = values[i]

            if prev_close == 0:
                continue

            daily_return = (curr_close / prev_close) - 1
            returns.append(daily_return)

        if len(returns) < 2:
            return None

        mean_return = sum(returns) / len(returns)

        variance = sum(
            (r - mean_return) ** 2 for r in returns
        ) / (len(returns) - 1)

        daily_vol = math.sqrt(variance)

        return daily_vol * math.sqrt(252)

    # ============================================================
    # Main Strategy Logic
    # ============================================================

    def run(self, data):

        allocations = {
            ticker: 0.0 for ticker in self.tickers
        }

        ohlcv = data["ohlcv"]

        # ========================================================
        # Minimum History Check
        # ========================================================

        if len(ohlcv) < 1:
            log("Insufficient historical data")
            return TargetAllocation(allocations)

        # ========================================================
        # Load Price Series
        # ========================================================

        prices = {}

        for ticker in self.tickers:

            closes = self.get_close_series(ohlcv, ticker)

            if len(closes) < 252:
                log(f"Insufficient data for {ticker}")
                return TargetAllocation(allocations)

            prices[ticker] = closes

        # ========================================================
        # Monthly Macro Regime Detection
        # ========================================================

        spy_monthly = self.monthly_series(prices["SPY"])
        gld_monthly = self.monthly_series(prices["GLD"])

        if len(spy_monthly) < 12:
            log("Insufficient monthly history")
            return TargetAllocation(allocations)

        ratio_series = []

        for i in range(len(spy_monthly)):

            if gld_monthly[i] == 0:
                ratio_series.append(0)
            else:
                ratio_series.append(
                    spy_monthly[i] / gld_monthly[i]
                )

        ratio_sma_12 = self.sma(ratio_series, 12)

        if ratio_sma_12 is None:
            return TargetAllocation(allocations)

        current_ratio = ratio_series[-1]

        risk_on_macro = current_ratio > ratio_sma_12

        # ========================================================
        # SPY Trend Filter
        # ========================================================

        spy_sma_10 = self.sma(spy_monthly, 10)

        if spy_sma_10 is None:
            return TargetAllocation(allocations)

        spy_trend = spy_monthly[-1] > spy_sma_10

        # ========================================================
        # Additional Trend Filters
        # ========================================================

        def trend_filter(ticker):

            monthly_prices = self.monthly_series(
                prices[ticker]
            )

            sma_10 = self.sma(monthly_prices, 10)

            if sma_10 is None:
                return False

            return monthly_prices[-1] > sma_10

        cwb_trend = trend_filter("CWB")
        tlt_trend = trend_filter("TLT")

        # ========================================================
        # Relative Strength Momentum
        # ========================================================

        momentum = {}

        for ticker in [
            "CWB",
            "HYG",
            "TLT",
            "IEF",
            "TIP",
            "SHY"
        ]:

            momentum[ticker] = self.momentum_return(
                prices[ticker],
                months=6
            )

        # ========================================================
        # Inflation Regime
        # ========================================================

        median_cpi_data = data.get(("median_cpi",))

        if (
            not median_cpi_data
            or len(median_cpi_data) < 1
        ):
            log("Missing CPI data")
            inflation_value = 2.5
        else:
            inflation_value = median_cpi_data[-1]["value"]

        inflationary_regime = inflation_value > 3.5

        # ========================================================
        # Risk-On Detection
        # ========================================================

        risk_on = risk_on_macro and spy_trend

        selected_asset = None

        # ========================================================
        # Risk-On Allocation Logic
        # ========================================================

        if risk_on:

            cwb_mom = momentum["CWB"]
            hyg_mom = momentum["HYG"]

            if (
                cwb_mom is not None
                and hyg_mom is not None
                and cwb_mom > hyg_mom
                and cwb_trend
            ):

                selected_asset = "CWB"

            else:
                selected_asset = "HYG"

            log(
                f"Risk-On regime | "
                f"Selected asset: {selected_asset}"
            )

        # ========================================================
        # Defensive Allocation Logic
        # ========================================================

        else:

            # --------------------------------------------
            # Inflationary Regime
            # --------------------------------------------

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

                log(
                    f"Inflationary regime | "
                    f"Selected asset: {selected_asset}"
                )

            # --------------------------------------------
            # Disinflationary Regime
            # --------------------------------------------

            else:

                tlt_mom = momentum["TLT"]
                ief_mom = momentum["IEF"]

                if (
                    tlt_mom is not None
                    and ief_mom is not None
                    and tlt_trend
                    and tlt_mom > ief_mom
                ):

                    selected_asset = "TLT"

                else:
                    selected_asset = "IEF"

                log(
                    f"Disinflationary regime | "
                    f"Selected asset: {selected_asset}"
                )

        # ========================================================
        # Volatility Targeting
        # ========================================================

        target_vol = 0.10

        realized_vol = self.annualized_volatility(
            prices[selected_asset],
            lookback=20
        )

        if realized_vol is None or realized_vol <= 0:
            exposure = 1.0
        else:
            exposure = target_vol / realized_vol

        # Exposure clipped between 0% and 100%
        exposure = max(0.0, min(1.0, exposure))

        # ========================================================
        # Final Portfolio Allocation
        # ========================================================

        allocations[selected_asset] = exposure

        log(
            f"Asset={selected_asset} | "
            f"Inflation={round(inflation_value, 2)} | "
            f"RiskOn={risk_on} | "
            f"Vol={round(realized_vol, 4) if realized_vol else 'N/A'} | "
            f"Exposure={round(exposure, 4)}"
        )

        return TargetAllocation(allocations)