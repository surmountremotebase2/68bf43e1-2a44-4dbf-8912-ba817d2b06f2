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

        self.trading_assets = [
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

        self.warmup = 252

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
            return None

        current = prices[-1]
        previous = prices[-1 - lookback]

        if (
            current is None
            or previous is None
            or previous == 0
        ):
            return None

        return (current / previous) - 1

    def trend_filter(self, ticker, ohlcv, closes):

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

    def calculate_realized_vol(
        self,
        prices,
        lookback=64
    ):

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
                or prev_price == 0
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

        return annualized_vol

    # ============================================================
    # MAIN STRATEGY
    # ============================================================

    def run(self, data):

        allocation = {
            ticker: 0.0
            for ticker in self.tickers
        }

        ohlcv = data["ohlcv"]

        if len(ohlcv) < self.warmup:

            log("Insufficient warmup data")

            return TargetAllocation(allocation)

        # ========================================================
        # CPI DATA
        # ========================================================

        median_cpi_data = data.get(("median_cpi",))

        latest_cpi = None

        if (
            median_cpi_data
            and len(median_cpi_data) > 0
        ):

            latest_cpi = median_cpi_data[-1]["value"]

        inflation_on = False

        if latest_cpi is not None:

            inflation_on = latest_cpi > 4

        # ========================================================
        # CLOSE PRICES
        # ========================================================

        closes = {}

        for ticker in self.tickers:

            closes[ticker] = []

            try:

                for bar in ohlcv:

                    if (
                        ticker in bar
                        and bar[ticker]
                        and "close" in bar[ticker]
                    ):

                        close_price = bar[ticker]["close"]

                        if close_price is not None:

                            closes[ticker].append(close_price)

            except Exception as e:

                log(f"Close extraction error {ticker}: {e}")

        # ========================================================
        # VALIDATION
        # ========================================================

        for ticker in self.tickers:

            if len(closes[ticker]) < self.warmup:

                log(f"Not enough history for {ticker}")

                return TargetAllocation(allocation)

        # ========================================================
        # SPY / GLD RATIO FILTER
        # ========================================================

        risk_on = False

        try:

            monthly_step = 21
            required_history = 12 * monthly_step

            if (
                len(closes["SPY"]) > required_history
                and len(closes["GLD"]) > required_history
            ):

                current_ratio = (
                    closes["SPY"][-1] /
                    closes["GLD"][-1]
                )

                ratio_history = []

                for i in range(1, 13):

                    idx = i * monthly_step

                    spy_price = closes["SPY"][-idx]
                    gld_price = closes["GLD"][-idx]

                    if gld_price != 0:

                        ratio = (
                            spy_price / gld_price
                        )

                        ratio_history.append(ratio)

                if len(ratio_history) > 0:

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

        # ========================================================
        # TREND FILTERS
        # ========================================================

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

        # ========================================================
        # MOMENTUM
        # ========================================================

        momentum_lookback = 126

        cwb_ret = self.compute_return(
            closes["CWB"],
            momentum_lookback
        )

        hyg_ret = self.compute_return(
            closes["HYG"],
            momentum_lookback
        )

        tlt_ret = self.compute_return(
            closes["TLT"],
            momentum_lookback
        )

        ief_ret = self.compute_return(
            closes["IEF"],
            momentum_lookback
        )

        tip_ret = self.compute_return(
            closes["TIP"],
            momentum_lookback
        )

        shy_ret = self.compute_return(
            closes["SHY"],
            momentum_lookback
        )

        # ========================================================
        # RISK ASSET
        # ========================================================

        risk_asset = "HYG"

        if (
            cwb_ret is not None
            and hyg_ret is not None
        ):

            if (
                cwb_ret > hyg_ret
                and cwb_bull
            ):

                risk_asset = "CWB"

        # ========================================================
        # DEFENSIVE ASSET
        # ========================================================

        defensive_asset = "IEF"

        if inflation_on:

            if (
                tip_ret is not None
                and shy_ret is not None
            ):

                if tip_ret > shy_ret:

                    defensive_asset = "TIP"

                else:

                    defensive_asset = "SHY"

        else:

            if (
                tlt_ret is not None
                and ief_ret is not None
            ):

                if (
                    tlt_ret > ief_ret
                    and tlt_bull
                ):

                    defensive_asset = "TLT"

                else:

                    defensive_asset = "IEF"

        # ========================================================
        # FINAL ASSET SELECTION
        # ========================================================

        if risk_on and spy_bull:

            selected_asset = risk_asset

        else:

            selected_asset = defensive_asset

        # ========================================================
        # VOLATILITY TARGETING
        # ========================================================

        realized_vol = self.calculate_realized_vol(
            closes[selected_asset],
            self.vol_lookback
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

        # ========================================================
        # FINAL ALLOCATION
        # ========================================================

        allocation[selected_asset] = round(
            leverage,
            4
        )

        # ========================================================
        # LOGGING
        # ========================================================

        #log(f"CPI: {latest_cpi}")
        #log(f"Inflation regime: {inflation_on}")
        log(f"Risk on: {risk_on}")
        #log(f"Risk asset: {risk_asset}")
        #log(f"Defensive asset: {defensive_asset}")
        log(f"Selected asset: {selected_asset}")
        log(f"Realized vol: {realized_vol}")
        #log(f"Leverage: {leverage}")

        return TargetAllocation(allocation)