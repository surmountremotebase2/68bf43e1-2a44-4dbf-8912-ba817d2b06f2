from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import pandas as pd
import pandas_ta as ta

class TradingStrategy(Strategy):
    def __init__(self):
        # We only need SPY and GLD for this rotation strategy
        self.tickers = ["GLD", "QQQ", "BIL"]
        self.data_list = []

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Daily interval used to build the long-term moving average
        return "1day"

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        ohlcv = data["ohlcv"]

        lookback = 50
        long_sma = 200

        # Ensure we have enough data to calculate EMA
        if len(ohlcv) < lookback:
            return TargetAllocation({})

        # Extract closing prices
        qqq_close = pd.Series([x["QQQ"]["close"] for x in ohlcv])
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv])

        # 1. Calculate the SPY/GLD ratio
        qqq_gld_ratio = qqq_close / gld_close

        # 2. Calculate the EMA for the ratio
        qqq_sma = 0
        gld_sma = 0
        if len(qqq_close) > long_sma:
            qqq_sma = ta.sma(qqq_close, length=long_sma).tolist()[-1]
            gld_sma = ta.sma(gld_close, length=long_sma).tolist()[-1]
        qqq_gld_ema50 = ta.sma(qqq_gld_ratio, length=lookback).tolist()
        qqq_gld_ema5 = ta.ema(qqq_gld_ratio, length=5).tolist()
        #current_ratio = spy_gld_ratio.tolist()[-1]
        current_ratio = qqq_gld_ema5[-1]
        current_ema = qqq_gld_ema50[-1]
        qqq_close_today = qqq_close.iloc[-1]
        gld_close_today = gld_close.iloc[-1]

        # Initialize base weights
        qqq_weight = 0.0
        gld_weight = 0.0
        bil_weight = 0.0

        # 3. Apply the rotation logic
        # If the ratio is above its EMA, we are in a Risk-On regime (Buy QQQ)
        # Otherwise, Risk-Off regime (Buy GLD)
        if current_ratio > current_ema and qqq_close_today > qqq_sma:
            qqq_weight = 1.0
        elif current_ratio < current_ema and gld_close_today > gld_sma:
            gld_weight = 1.0
        else:
            bil_weight = 1.0

        # Log the current state for backtesting transparency
        #log(f"QQQ/GLD Ratio: {current_ratio:.4f} | EMA: {current_ema:.4f} -> Allocating QQQ: {qqq_weight}, GLD: {gld_weight}")

        return TargetAllocation({
            "QQQ": qqq_weight,
            "GLD": gld_weight,
            "BIL": bil_weight
        })