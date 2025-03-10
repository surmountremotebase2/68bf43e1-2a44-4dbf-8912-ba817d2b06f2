from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from surmount.technical_indicators import (
    RSI, SMA, EMA, MACD, MFI, BB, Slope, ADX, CCI, PPO, SO, WillR, STDEV, 
    VWAP, Momentum, PSAR, OBV, ATR
)

class TradingStrategy(Strategy):
    """
    A simple buy-and-hold strategy for QQQ that logs all available technical indicators.
    """

    @property
    def assets(self):
        """Define the asset to trade: QQQ."""
        return ["QQQ"]

    @property
    def interval(self):
        """Set the data interval to daily."""
        return "1day"

    @property
    def data(self):
        """No additional data sources needed for this strategy."""
        return []

    def run(self, data):
        """
        Execute the strategy: allocate 100% to QQQ and log all technical indicators.

        :param data: Dictionary containing OHLCV data and other specified data sources.
        :return: TargetAllocation object with the portfolio allocation.
        """
        # Access OHLCV data
        ohlcv_data = data["ohlcv"]
        ticker = "QQQ"

        # Check if there is sufficient data to compute indicators
        if not ohlcv_data or len(ohlcv_data) < 20:
            log("Insufficient data to compute indicators.")
            return TargetAllocation({"QQQ": 1.0})  # Default to full allocation if data is lacking

        # Log all available technical indicators
        log(f"--- Technical Indicators for {ticker} ---")

        # RSI (Relative Strength Index)
        rsi = RSI(ticker, ohlcv_data, length=14)
        if rsi: log(f"RSI (14): {rsi[-1]}")

        # SMA (Simple Moving Average)
        sma = SMA(ticker, ohlcv_data, length=20)
        if sma: log(f"SMA (20): {sma[-1]}")

        # EMA (Exponential Moving Average)
        ema = EMA(ticker, ohlcv_data, length=20)
        if ema: log(f"EMA (20): {ema[-1]}")

        # MACD (Moving Average Convergence Divergence)
        macd = MACD(ticker, ohlcv_data, fast=12, slow=26)
        if macd:
            log(f"MACD (12, 26): MACD={macd['MACD_12_26_9'][-1]}, Signal={macd['MACDs_12_26_9'][-1]}, Histogram={macd['MACDh_12_26_9'][-1]}")

        # MFI (Money Flow Index)
        mfi = MFI(ticker, ohlcv_data, length=14)
        if mfi: log(f"MFI (14): {mfi[-1]}")

        # BB (Bollinger Bands)
        bb = BB(ticker, ohlcv_data, length=20, std=2.0)
        if bb:
            log(f"Bollinger Bands (20, 2): Upper={bb['upper'][-1]}, Mid={bb['mid'][-1]}, Lower={bb['lower'][-1]}")

        # Slope
        slope = Slope(ticker, ohlcv_data, length=14)
        if slope: log(f"Slope (14): {slope[-1]}")

        # ADX (Average Directional Index)
        adx = ADX(ticker, ohlcv_data, length=14)
        if adx: log(f"ADX (14): {adx[-1]}")

        # CCI (Commodity Channel Index)
        cci = CCI(ticker, ohlcv_data, length=20)
        if cci: log(f"CCI (20): {cci[-1]}")

        # PPO (Percentage Price Oscillator)
        ppo = PPO(ticker, ohlcv_data, fast=12, slow=26)
        if ppo: log(f"PPO (12, 26): {ppo[-1]}")

        # SO (Stochastic Oscillator)
        so = SO(ticker, ohlcv_data)
        if so: log(f"Stochastic Oscillator: {so[-1]}")

        # WillR (Williams %R)
        willr = WillR(ticker, ohlcv_data, length=14)
        if willr: log(f"Williams %R (14): {willr[-1]}")

        # STDEV (Standard Deviation)
        stdev = STDEV(ticker, ohlcv_data, length=20)
        if stdev: log(f"STDEV (20): {stdev[-1]}")

        # VWAP (Volume Weighted Average Price)
        vwap = VWAP(ticker, ohlcv_data, length=14)
        if vwap: log(f"VWAP (14): {vwap[-1]}")

        # Momentum
        momentum = Momentum(ticker, ohlcv_data, length=10)
        if momentum: log(f"Momentum (10): {momentum[-1]}")

        # PSAR (Parabolic SAR)
        psar = PSAR(ticker, ohlcv_data)
        if psar:
            log(f"PSAR: PSARl={psar.get('PSARl_0.02_0.2', [])[-1] if psar.get('PSARl_0.02_0.2') else 'N/A'}, "
                f"PSARs={psar.get('PSARs_0.02_0.2', [])[-1] if psar.get('PSARs_0.02_0.2') else 'N/A'}")

        # OBV (On-Balance Volume)
        obv = OBV(ticker, ohlcv_data, length=14)
        if obv: log(f"OBV (14): {obv[-1]}")

        # ATR (Average True Range)
        atr = ATR(ticker, ohlcv_data, length=14)
        if atr: log(f"ATR (14): {atr[-1]}")

        # Buy-and-hold strategy: always allocate 100% to QQQ
        allocation_dict = {"QQQ": 1.0}
        log(f"Allocation: {allocation_dict}")

        return TargetAllocation(allocation_dict)