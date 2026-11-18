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
        ohlcv = data["ohlcv"]

        lookback = 50
        long_sma = 300

        # Enforce minimum 300-bar history required for valid 300-day SMA calculation;
        # park capital in 1-3 Month U.S. Treasury Bills (BIL) during warm-up period.
        if len(ohlcv) < lookback:
            return TargetAllocation({})

        # Extract daily closing price series for QQQ and GLD
        qqq_close = pd.Series([x["QQQ"]["close"] for x in ohlcv])
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv])

        # 1. Calculate the daily QQQ/GLD relative price ratio
        qqq_gld_ratio = qqq_close / gld_close

        
        # 2. Calculate 300-day SMAs for absolute trend filtering and 5-EMA / 50-SMA for ratio momentum
        qqq_sma = 0
        gld_sma = 0
        if len(qqq_close) > long_sma:
            qqq_sma = ta.sma(qqq_close, length=long_sma).tolist()[-1]
            gld_sma = ta.sma(gld_close, length=long_sma).tolist()[-1]
        qqq_gld_ema50 = ta.sma(qqq_gld_ratio, length=lookback).tolist()
        qqq_gld_ema5 = ta.ema(qqq_gld_ratio, length=5).tolist()
        current_ratio = qqq_gld_ema5[-1]
        current_ema = qqq_gld_ema50[-1]
        qqq_close_today = qqq_close.iloc[-1]
        gld_close_today = gld_close.iloc[-1]

        # Initialize mutually exclusive target weights (100% single-asset allocation)
        qqq_weight = 0.0
        gld_weight = 0.0
        bil_weight = 0.0

        # 3. Apply dual-condition tactical rotation logic:
        # - Allocate 100% QQQ if 5-EMA(QQQ/GLD) > 50-SMA(QQQ/GLD) AND QQQ > 300-day SMA
        # - Allocate 100% GLD if 5-EMA(QQQ/GLD) < 50-SMA(QQQ/GLD) AND GLD > 300-day SMA
        # - Otherwise allocate 100% BIL (defensive U.S. Treasury Bills fallback)
        if current_ratio > current_ema and qqq_close_today > qqq_sma:
            qqq_weight = 1.0
        elif current_ratio < current_ema and gld_close_today > gld_sma:
            gld_weight = 1.0
        else:
            bil_weight = 1.0

        # Log the current state for backtesting transparency
        #log(
        #    f"QQQ/GLD 5-EMA: {current_ratio_ema5:.4f} | 50-SMA: {current_ratio_sma50:.4f} | "
        #    f"QQQ: {qqq_close_today:.2f} (SMA300: {qqq_sma:.2f}) | "
        #    f"GLD: {gld_close_today:.2f} (SMA300: {gld_sma:.2f}) -> "
        #    f"Allocation QQQ: {qqq_weight}, GLD: {gld_weight}, BIL: {bil_weight}"
        #)

        return TargetAllocation({
            "QQQ": qqq_weight,
            "GLD": gld_weight,
            "BIL": bil_weight
        })