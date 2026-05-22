from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA, STDEV
from surmount.data import MedianCPI
from surmount.logging import log


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
        self.min_leverage = 0.0

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

        return closes[-1] > sma[-1]

    # ============================================================
    # MAIN STRATEGY
    # ============================================================

    def run(self, data):

        allocation = {
            ticker: 0.0
            for ticker in self.tickers
        }

        ohlcv = data["ohlcv"]

        warmup = 1

        if len(ohlcv) < warmup:
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

            try:

                closes[ticker] = [
                    bar[ticker]["close"]
                    for bar in ohlcv
                    if (
                        ticker in bar
                        and bar[ticker]["close"] is not None
                    )
                ]

            except Exception:

                closes[ticker] = []

        # Ensure all assets have enough history
        for ticker in self.tickers:

            if len(closes[ticker]) < warmup:

                log(f"Not enough data for {ticker}")

                return TargetAllocation(allocation)

        # ========================================================
        # SPY / GLD RATIO FILTER
        # ========================================================

        monthly_step = 21

        try:

            current_ratio = (
                closes["SPY"][-1] /
                closes["GLD"][-1]
            )

            ratio_history = []

            for i in range(12):

                idx = -(i + 1) * monthly_step

                ratio = (
                    closes["SPY"][idx] /
                    closes["GLD"][idx]
                )

                ratio_history.append(ratio)

            ratio_sma = (
                sum(ratio_history) /
                len(ratio_history)
            )

            risk_on = current_ratio > ratio_sma

        except Exception:

            log("Ratio filter failed")

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

        hyg_bull = self.trend_filter(
            "HYG",
            ohlcv,
            closes["HYG"]
        )

        # ========================================================
        # MOMENTUM
        # ========================================================

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

        # ========================================================
        # RISK ASSET
        # ========================================================

        if (
            cwb_ret is not None
            and hyg_ret is not None
            and cwb_ret > hyg_ret
            and cwb_bull
        ):

            risk_asset = "CWB"

        else:

            risk_asset = "HYG"

        # ========================================================
        # DEFENSIVE ASSET
        # ========================================================

        if inflation_on:

            if (
                tip_ret is not None
                and shy_ret is not None
                and tip_ret > shy_ret
            ):

                defensive_asset = "TIP"

            else:

                defensive_asset = "SHY"

        else:

            if (
                tlt_ret is not None
                and ief_ret is not None
                and tlt_ret > ief_ret
                and tlt_bull
            ):

                defensive_asset = "TLT"

            else:

                defensive_asset = "IEF"

        # ========================================================
        # FINAL SELECTION
        # ========================================================

        if risk_on and spy_bull:

            selected_asset = risk_asset

            log(f"Risk-on regime: {selected_asset}")

        else:

            selected_asset = defensive_asset

            log(f"Defensive regime: {selected_asset}")

        # ========================================================
        # VOLATILITY TARGETING
        # ========================================================

        leverage = 0.0

        try:

            stdev = STDEV(
                selected_asset,
                ohlcv,
                length=self.vol_lookback
            )

            if (
                stdev is not None
                and len(stdev) > 0
                and stdev[-1] is not None
            ):

                realized_vol = (
                    (
                        stdev[-1] /
                        closes[selected_asset][-1]
                    )
                    * (252 ** 0.5)
                )

                if realized_vol > 0:

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

        except Exception as e:

            log(f"Vol targeting error: {e}")

            leverage = 0.0

        # ========================================================
        # FINAL ALLOCATION
        # ========================================================

        allocation[selected_asset] = round(leverage, 4)

        total_alloc = sum(allocation.values())

        if total_alloc > 1:

            allocation = {
                k: v / total_alloc
                for k, v in allocation.items()
            }

        log(f"Selected asset: {selected_asset}")
        #log(f"CPI: {latest_cpi}")
        #log(f"Leverage: {leverage}")

        return TargetAllocation(allocation)