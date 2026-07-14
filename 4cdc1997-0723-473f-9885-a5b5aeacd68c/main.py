from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import pandas as pd
import pandas_ta as ta

class TradingStrategy(Strategy):
    def __init__(self):
        # We only need SPY and GLD for this rotation strategy
        self.tickers = ["SPY", "GLD"]
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

        # 20 months is approximately 420 trading days (20 * ~21 days/month)
        lookback = 50

        # Ensure we have enough data to calculate a 420-period EMA
        if len(ohlcv) < lookback:
            return TargetAllocation({})

        # Extract closing prices
        spy_close = pd.Series([x["SPY"]["close"] for x in ohlcv])
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv])

        # 1. Calculate the SPY/GLD ratio
        spy_gld_ratio = spy_close / gld_close

        # 2. Calculate the 20-month (420-day) EMA for the ratio
        spy_gld_ema50 = ta.ema(spy_gld_ratio, length=lookback).tolist()
        spy_gld_ema3 = ta.ema(spy_gld_ratio, length=2).tolist()
        current_ratio = spy_gld_ratio.tolist()[-1]
        #current_ratio = spy_gld_ema3[-1]
        current_ema = spy_gld_ema50[-1]

        # Initialize base weights
        spy_weight = 0.0
        gld_weight = 0.0

        # 3. Apply the rotation logic
        # If the ratio is above its 20-month EMA, we are in a Risk-On regime (Buy SPY)
        # Otherwise, Risk-Off regime (Buy GLD)
        if current_ratio > current_ema:
            spy_weight = 1.0
        else:
            gld_weight = 1.0

        # Log the current state for backtesting transparency
        #log(f"SPY/GLD Ratio: {current_ratio:.4f} | 20M EMA: {current_ema:.4f} -> Allocating SPY: {spy_weight}, GLD: {gld_weight}")

        return TargetAllocation({
            "SPY": spy_weight,
            "GLD": gld_weight
        })