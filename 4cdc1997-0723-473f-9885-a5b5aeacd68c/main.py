from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import pandas as pd
import pandas_ta as ta

class TradingStrategy(Strategy):
    def __init__(self):
        # We only need SPY and GLD for this rotation strategy
        self.tickers = ["GLD", "QQQ"]
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

        lookback = 400

        # Ensure we have enough data to calculate EMA
        if len(ohlcv) < lookback:
            return TargetAllocation({})

        # Extract closing prices
        qqq_close = pd.Series([x["QQQ"]["close"] for x in ohlcv])
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv])

        # 1. Calculate the SPY/GLD ratio
        qqq_gld_ratio = qqq_close / gld_close

        # 2. Calculate the EMA for the ratio
        qqq_gld_ema50 = ta.sma(qqq_gld_ratio, length=lookback).tolist()
        qqq_gld_ema5 = ta.ema(qqq_gld_ratio, length=5).tolist()
        #current_ratio = spy_gld_ratio.tolist()[-1]
        current_ratio = qqq_gld_ema5[-1]
        current_ema = qqq_gld_ema50[-1]

        # Initialize base weights
        qqq_weight = 0.0
        gld_weight = 0.0

        # 3. Apply the rotation logic
        # If the ratio is above its EMA, we are in a Risk-On regime (Buy QQQ)
        # Otherwise, Risk-Off regime (Buy GLD)
        if current_ratio > current_ema:
            qqq_weight = 1.0
        else:
            gld_weight = 1.0

        # Log the current state for backtesting transparency
        #log(f"QQQ/GLD Ratio: {current_ratio:.4f} | EMA: {current_ema:.4f} -> Allocating QQQ: {qqq_weight}, GLD: {gld_weight}")

        return TargetAllocation({
            "QQQ": qqq_weight,
            "GLD": gld_weight
        })