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
        self.max_leverage = 1.0
        self.min_leverage = 0.25
        self.warmup = 2

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

    def compute_return(self, prices, lookback):

        if len(prices) <= lookback:
            return 0.0

        current = prices[-1]
        previous = prices[-1 - lookback]

        if (
            current is None
            or previous is None
            or previous == 0
        ):
            return 0.0

        return (current / previous) - 1

    def trend_filter(self, ticker, ohlcv, closes):

        try:

            sma = SMA(
                ticker,
                ohlcv,
                length=210
            )

            if (
                sma is None
                or len(sma) == 0
                or sma[-1] is None
            ):
                return False

            if len(closes) == 0:
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

                daily_return = (
                    curr_price / prev_price
                ) - 1

                returns.append(daily_return)

            if len(returns) < 10:
                return None

            mean_return = (
                sum(returns) / len(returns)
            )

            variance = sum(
                (r - mean_return) ** 2
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

            inflation_on = latest_cpi > 4

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
            # SPY / GLD RATIO FILTER
            # ====================================================

            risk_on = False

            try:

                monthly_step = 21

                ratio_history = []

                max_months = min(
                    12,
                    int(
                        min(
                            len(closes["SPY"]),
                            len(closes["GLD"])
                        ) / monthly_step
                    ) - 1
                )

                for i in range(1, max_months + 1):

                    idx = i * monthly_step

                    spy_price = closes["SPY"][-idx]
                    gld_price = closes["GLD"][-idx]

                    if gld_price > 0:

                        ratio_history.append(
                            spy_price / gld_price
                        )

                if len(ratio_history) >= 3:

                    current_ratio = (
                        closes["SPY"][-1] /
                        closes["GLD"][-1]
                    )

                    ratio_sma = (
                        sum(ratio_history) /
                        len(ratio_history)
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

            tlt_bull = self.trend_filter(
                "TLT",
                ohlcv,
                closes["TLT"]
            )

            cwb_bull = self.trend_filter(
                "CWB",
                ohlcv,
                closes["CWB"]
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
            # RISK ASSET
            # ====================================================

            risk_asset = "HYG"

            if (
                cwb_ret > hyg_ret
                and cwb_bull
            ):

                risk_asset = "CWB"

            # ====================================================
            # DEFENSIVE ASSET
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
            # FINAL ASSET
            # ====================================================

            if risk_on and spy_bull:

                selected_asset = risk_asset

            else:

                selected_asset = defensive_asset

            # ====================================================
            # VOL TARGETING
            # ====================================================

            realized_vol = (
                self.calculate_realized_vol(
                    closes[selected_asset],
                    self.vol_lookback
                )
            )

            if (
                realized_vol is None
                or realized_vol <= 0
            ):

                leverage = self.min_leverage

            else:

                leverage = (
                    self.target_vol /
                    realized_vol
                )

                leverage = max(
                    self.min_leverage,
                    min(
                        leverage,
                        self.max_leverage
                    )
                )

            # Final hard validation
            if (
                leverage is None
                or math.isnan(leverage)
                or math.isinf(leverage)
            ):

                leverage = self.min_leverage

            allocation[selected_asset] = round(
                float(leverage),
                4
            )

            # ====================================================
            # LOGS
            # ====================================================

            log(f"Risk on: {risk_on}")
            log(f"Selected asset: {selected_asset}")
            log(f"Realized vol: {realized_vol}")
            log(f"Leverage: {leverage}")

            return TargetAllocation(allocation)

        except Exception as e:

            log(f"Strategy runtime error: {e}")

            return TargetAllocation(allocation)