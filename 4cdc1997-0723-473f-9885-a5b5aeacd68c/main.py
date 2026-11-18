from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import pandas as pd
import pandas_ta as ta


class TradingStrategy(Strategy):
    def __init__(self):
        # Universe consists of Nasdaq-100 Equities (QQQ), Gold (GLD), and 1-3M T-Bills (BIL)
        self.tickers = ["GLD", "QQQ", "BIL"]
        self.data_list = []

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Daily interval used to evaluate relative ratio momentum and 300-day SMA trend filters
        return "1day"

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        ohlcv = data.get("ohlcv", [])

        ratio_fast_ema = 5
        ratio_slow_sma = 50
        long_sma = 300

        # Enforce minimum 300-bar history required for valid 300-day SMA calculation;
        # park capital in 1-3 Month U.S. Treasury Bills (BIL) during warm-up period.
        if len(ohlcv) < long_sma:
            return TargetAllocation({"QQQ": 0.0, "GLD": 0.0, "BIL": 1.0})

        # Extract daily closing price series for QQQ and GLD
        qqq_close = pd.Series([x["QQQ"]["close"] for x in ohlcv], dtype=float)
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv], dtype=float)

        # Guard against zero or missing prices prior to ratio division
        if (gld_close <= 0).any() or qqq_close.isna().any() or gld_close.isna().any():
            log("Invalid or zero price detected; defaulting to 100% BIL.")
            return TargetAllocation({"QQQ": 0.0, "GLD": 0.0, "BIL": 1.0})

        # 1. Calculate the daily QQQ/GLD relative price ratio
        qqq_gld_ratio = qqq_close / gld_close

        # 2. Calculate 300-day SMAs for absolute trend filtering and 5-EMA / 50-SMA for ratio momentum
        qqq_sma_series = ta.sma(qqq_close, length=long_sma)
        gld_sma_series = ta.sma(gld_close, length=long_sma)
        ratio_sma50_series = ta.sma(qqq_gld_ratio, length=ratio_slow_sma)
        ratio_ema5_series = ta.ema(qqq_gld_ratio, length=ratio_fast_ema)

        if (
            qqq_sma_series is None
            or gld_sma_series is None
            or ratio_sma50_series is None
            or ratio_ema5_series is None
        ):
            return TargetAllocation({"QQQ": 0.0, "GLD": 0.0, "BIL": 1.0})

        qqq_sma = qqq_sma_series.iloc[-1]
        gld_sma = gld_sma_series.iloc[-1]
        current_ratio_ema5 = ratio_ema5_series.iloc[-1]
        current_ratio_sma50 = ratio_sma50_series.iloc[-1]
        qqq_close_today = qqq_close.iloc[-1]
        gld_close_today = gld_close.iloc[-1]

        if pd.isna([qqq_sma, gld_sma, current_ratio_ema5, current_ratio_sma50]).any():
            return TargetAllocation({"QQQ": 0.0, "GLD": 0.0, "BIL": 1.0})

        # Initialize mutually exclusive target weights (100% single-asset allocation)
        qqq_weight = 0.0
        gld_weight = 0.0
        bil_weight = 0.0

        # 3. Apply dual-condition tactical rotation logic:
        # - Allocate 100% QQQ if 5-EMA(QQQ/GLD) > 50-SMA(QQQ/GLD) AND QQQ > 300-day SMA
        # - Allocate 100% GLD if 5-EMA(QQQ/GLD) < 50-SMA(QQQ/GLD) AND GLD > 300-day SMA
        # - Otherwise allocate 100% BIL (defensive U.S. Treasury Bills fallback)
        if current_ratio_ema5 > current_ratio_sma50 and qqq_close_today > qqq_sma:
            qqq_weight = 1.0
        elif current_ratio_ema5 < current_ratio_sma50 and gld_close_today > gld_sma:
            gld_weight = 1.0
        else:
            bil_weight = 1.0

        return TargetAllocation({
            "QQQ": qqq_weight,
            "GLD": gld_weight,
            "BIL": bil_weight
        })