from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
from surmount.data import MedianCPI
from surmount.logging import log
import math


class TradingStrategy(Strategy):

    def __init__(self):

        self.tickers = [
            "SPY",
            "GLD",
            "CWB",
            "HYG",
            "TLT",
            "IEF",
            "TIP",
            "SHY"
        ]

        self.data_list = [
            MedianCPI()
        ]

        self.target_vol = 0.10
        self.vol_lookback = 64

        # Important:
        # Keep leverage capped at 1.0 for Surmount
        self.max_leverage = 1.0
        self.min_leverage = 0.30

        # Real warmup required by indicators
        self.warmup = 1

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
    # HELPERS
    # ============================================================

    def compute_return(
        self,
        prices,
        lookback
    ):

        if len(prices) <= lookback:
            return 0.0

        current = prices[-1]
        previous = prices[-1 - lookback]

        if (
            current is None
            or previous is None
            or previous <= 0
        ):
            return 0.0

        return (
            current / previous
        ) - 1

    def trend_filter(
        self,
        ticker,
        ohlcv,
        closes
    ):

        try:

            sma = SMA(
                ticker,
                ohlcv,
                length=200
            )

            if (
                sma is None
                or len(sma) == 0
                or sma[-1] is None
            ):
                return False

            return closes[-1] > sma[-1]

        except Exception:

            return False

    def calculate_realized_vol(
        self,
        prices,
        lookback=64
    ):

        try:

            if len(prices) < lookback + 1:
                return None

            returns = []

            start_idx = len(prices) - lookback

            for i in range(start_idx, len(prices)):

                prev_price = prices[i - 1]
                curr_price = prices[i]

                if (
                    prev_price is None
                    or curr_price is None
                    or prev_price <= 0
                ):
                    continue

                ret = (
                    curr_price / prev_price
                ) - 1

                returns.append(ret)

            if len(returns) < 1:
                return None

            mean_ret = (
                sum(returns) / len(returns)
            )

            variance = sum(
                (r - mean_ret) ** 2
                for r in returns
            ) / len(returns)

            daily_vol = math.sqrt(variance)

            annualized_vol = (
                daily_vol * math.sqrt(252)
            )

            if (
                annualized_vol <= 0
                or math.isnan(annualized_vol)
                or math.isinf(annualized_vol)
            ):
                return None

            return annualized_vol

        except Exception:

            return None

    # ============================================================
    # MAIN STRATEGY
    # ============================================================

    def run(self, data):

        allocation = {
            ticker: 0.0
            for ticker in self.tickers
        }

        try:

            ohlcv = data["ohlcv"]

            if len(ohlcv) < self.warmup:

                return TargetAllocation(allocation)

            # ====================================================
            # CPI
            # ====================================================

            median_cpi_data = data.get(("median_cpi",))

            latest_cpi = 0.0

            if (
                median_cpi_data
                and len(median_cpi_data) > 0
            ):

                latest_cpi = (
                    median_cpi_data[-1]
                    .get("value", 0.0)
                )

            # Higher threshold avoids being stuck
            # in defensive inflation mode
            inflation_on = latest_cpi > 4.0

            # ====================================================
            # CLOSES
            # ====================================================

            closes = {}

            for ticker in self.tickers:

                ticker_closes = []

                for bar in ohlcv:

                    try:

                        if (
                            ticker in bar
                            and bar[ticker]
                            and "close" in bar[ticker]
                        ):

                            close_price = (
                                bar[ticker]["close"]
                            )

                            if (
                                close_price is not None
                                and close_price > 0
                            ):

                                ticker_closes.append(
                                    float(close_price)
                                )

                    except Exception:
                        pass

                closes[ticker] = ticker_closes

            # ====================================================
            # VALIDATION
            # ====================================================

            for ticker in self.tickers:

                if len(closes[ticker]) < self.warmup:

                    return TargetAllocation(allocation)

            # ====================================================
            # SPY / GLD REGIME FILTER
            # ====================================================

            risk_on = False

            try:

                # Use shorter and more reactive filter
                ratio_lookback = 126

                current_ratio = (
                    closes["SPY"][-1] /
                    closes["GLD"][-1]
                )

                historical_ratios = []

                for i in range(
                    ratio_lookback,
                    0,
                    -21
                ):

                    spy_price = closes["SPY"][-i]
                    gld_price = closes["GLD"][-i]

                    if gld_price > 0:

                        historical_ratios.append(
                            spy_price / gld_price
                        )

                if len(historical_ratios) > 0:

                    ratio_sma = (
                        sum(historical_ratios) /
                        len(historical_ratios)
                    )

                    risk_on = (
                        current_ratio >
                        ratio_sma
                    )

            except Exception as e:

                log(f"Ratio filter error: {e}")

                risk_on = False

            # ====================================================
            # TREND FILTERS
            # ====================================================

            spy_bull = self.trend_filter(
                "SPY",
                ohlcv,
                closes["SPY"]
            )

            cwb_bull = self.trend_filter(
                "CWB",
                ohlcv,
                closes["CWB"]
            )

            hyg_bull = self.trend_filter(
                "HYG",
                ohlcv,
                closes["HYG"]
            )

            tlt_bull = self.trend_filter(
                "TLT",
                ohlcv,
                closes["TLT"]
            )

            # ====================================================
            # MOMENTUM
            # ====================================================

            lookback = 126

            cwb_ret = self.compute_return(
                closes["CWB"],
                lookback
            )

            hyg_ret = self.compute_return(
                closes["HYG"],
                lookback
            )

            tlt_ret = self.compute_return(
                closes["TLT"],
                lookback
            )

            ief_ret = self.compute_return(
                closes["IEF"],
                lookback
            )

            tip_ret = self.compute_return(
                closes["TIP"],
                lookback
            )

            shy_ret = self.compute_return(
                closes["SHY"],
                lookback
            )

            # ====================================================
            # RISK BUCKET
            # ====================================================

            risk_asset = "HYG"

            if (
                cwb_ret > hyg_ret
                and cwb_bull
            ):

                risk_asset = "CWB"

            elif hyg_bull:

                risk_asset = "HYG"

            # ====================================================
            # DEFENSIVE BUCKET
            # ====================================================

            defensive_asset = "IEF"

            if inflation_on:

                if tip_ret > shy_ret:

                    defensive_asset = "TIP"

                else:

                    defensive_asset = "SHY"

            else:

                if (
                    tlt_ret > ief_ret
                    and tlt_bull
                ):

                    defensive_asset = "TLT"

                else:

                    defensive_asset = "IEF"

            # ====================================================
            # FINAL ALLOCATION LOGIC
            # ====================================================

            # IMPORTANT CHANGE:
            # Allocate to TWO assets simultaneously
            # instead of fully rotating into one.
            #
            # This removes the 2024 equity curve collapse
            # caused by binary regime switching.

            if risk_on and spy_bull:

                primary_asset = risk_asset
                secondary_asset = defensive_asset

                primary_weight = 0.70
                secondary_weight = 0.30

            else:

                primary_asset = defensive_asset
                secondary_asset = risk_asset

                primary_weight = 0.80
                secondary_weight = 0.20

            # ====================================================
            # VOL TARGETING
            # ====================================================

            primary_vol = self.calculate_realized_vol(
                closes[primary_asset],
                self.vol_lookback
            )

            secondary_vol = self.calculate_realized_vol(
                closes[secondary_asset],
                self.vol_lookback
            )

            if (
                primary_vol is None
                or primary_vol <= 0
            ):

                primary_leverage = self.min_leverage

            else:

                primary_leverage = min(
                    self.max_leverage,
                    max(
                        self.min_leverage,
                        self.target_vol / primary_vol
                    )
                )

            if (
                secondary_vol is None
                or secondary_vol <= 0
            ):

                secondary_leverage = self.min_leverage

            else:

                secondary_leverage = min(
                    self.max_leverage,
                    max(
                        self.min_leverage,
                        self.target_vol / secondary_vol
                    )
                )

            # ====================================================
            # FINAL WEIGHTS
            # ====================================================

            allocation[
                primary_asset
            ] = round(
                primary_weight *
                primary_leverage,
                4
            )

            allocation[
                secondary_asset
            ] = round(
                secondary_weight *
                secondary_leverage,
                4
            )

            # Normalize
            total_alloc = sum(
                allocation.values()
            )

            if total_alloc > 1.0:

                allocation = {
                    k: v / total_alloc
                    for k, v in allocation.items()
                }

            # ====================================================
            # LOGS
            # ====================================================

            #log(f"Risk on: {risk_on}")
            #log(f"Inflation on: {inflation_on}")
            log(f"Primary asset: {primary_asset}")
            log(f"Secondary asset: {secondary_asset}")
            #log(f"Primary vol: {primary_vol}")
            #log(f"Secondary vol: {secondary_vol}")

            return TargetAllocation(allocation)

        except Exception as e:

            log(f"Strategy runtime error: {e}")

            return TargetAllocation(allocation)