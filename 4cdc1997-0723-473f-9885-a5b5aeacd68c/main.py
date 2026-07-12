from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import pandas as pd
import pandas_ta as ta

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the universe of tickers for both signal generation and allocation
        self.tickers = ["SPY", "GLD", "TLT", "QQQ"]
        
        # We only need standard price data (OHLCV), so no extra datasets are required
        self.data_list = []

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # 1-day interval is required to compute 100-day EMAs accurately
        return "1day"

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        ohlcv = data["ohlcv"]

        # Ensure we have enough data to calculate a 100-period EMA
        if len(ohlcv) < 100:
            return TargetAllocation({})

        # Extract closing prices for the ratio calculations
        # Using a list comprehension ensures we only grab the 'close' price for each required ticker
        spy_close = pd.Series([x["SPY"]["close"] for x in ohlcv])
        gld_close = pd.Series([x["GLD"]["close"] for x in ohlcv])
        tlt_close = pd.Series([x["TLT"]["close"] for x in ohlcv])

        # 1. Calculate the ratios
        spy_gld_ratio = spy_close / gld_close
        spy_tlt_ratio = spy_close / tlt_close
        gld_tlt_ratio = gld_close / tlt_close

        # 2. Calculate the 3-day and 100-day EMAs for each ratio
        # SPY/GLD EMAs
        spy_gld_ema3 = ta.ema(spy_gld_ratio, length=3).tolist()
        spy_gld_ema100 = ta.ema(spy_gld_ratio, length=100).tolist()

        # SPY/TLT EMAs
        spy_tlt_ema3 = ta.ema(spy_tlt_ratio, length=3).tolist()
        spy_tlt_ema100 = ta.ema(spy_tlt_ratio, length=100).tolist()

        # GLD/TLT EMAs
        gld_tlt_ema3 = ta.ema(gld_tlt_ratio, length=3).tolist()
        gld_tlt_ema100 = ta.ema(gld_tlt_ratio, length=100).tolist()

        # Initialize base weights
        qqq_weight = 0.0
        gld_weight = 0.0
        tlt_weight = 0.0

        # 3. Apply the logic rules
        
        # Rule 1: SPY/GLD Ratio
        if spy_gld_ema3[-1] > spy_gld_ema100[-1]:
            qqq_weight += 0.33
        else:
            gld_weight += 0.33

        # Rule 2: SPY/TLT Ratio
        if spy_tlt_ema3[-1] > spy_tlt_ema100[-1]:
            gld_weight += 0.33
        else:
            tlt_weight += 0.33

        # Rule 3: GLD/TLT Ratio
        if gld_tlt_ema3[-1] > gld_tlt_ema100[-1]:
            gld_weight += 0.33
        else:
            tlt_weight += 0.33

        # 4. Normalize the weights
        # The sum of weights above equals 1.5. To keep it between 0 and 1, we divide by the total.
        total_weight = qqq_weight + gld_weight + tlt_weight
        
        if total_weight > 0:
            qqq_weight /= total_weight
            gld_weight /= total_weight
            tlt_weight /= total_weight

        # Log the final intended allocations for backtesting transparency
        log(f"Allocating -> QQQ: {qqq_weight:.2f}, GLD: {gld_weight:.2f}, TLT: {tlt_weight:.2f}")

        return TargetAllocation({
            "QQQ": qqq_weight,
            "GLD": gld_weight,
            "TLT": tlt_weight
        })