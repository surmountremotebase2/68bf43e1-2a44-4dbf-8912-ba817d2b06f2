from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB, ATR, SMA
from surmount.logging import log
import pandas as pd

class TradingStrategy(Strategy):
    def __init__(self):
        # Focus tickers for the strategy
        self.tickers = ["QQQ"]
        # In the Surmount framework, we use ohlcv data directly. 
        # For ATR% calculations, we leverage the daily interval.
        self.data_list = [] 

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # We use 1hour to simulate the intraday logic mentioned in Section 2
        return "1hour"

    def run(self, data):
        """
        Implementation of the ATR-based volatility scaling and mean reversion strategy.
        """
        ohlcv = data["ohlcv"]
        allocation_dict = {ticker: 0 for ticker in self.tickers}
        
        # Minimum data requirement for 14-period ATR and 20-period BB
        if len(ohlcv) < 21:
            return TargetAllocation(allocation_dict)

        for ticker in self.tickers:
            # 1. Compute Technical Indicators
            # Bollinger Bands for mean reversion entry
            bb_data = BB(ticker, ohlcv, 20, 2)
            # ATR for volatility measurement
            atr_values = ATR(ticker, ohlcv, 14)
            # SMA for trend filtering
            sma_fast = SMA(ticker, ohlcv, 50)
            
            if bb_data is None or atr_values is None or sma_fast is None:
                continue

            current_price = ohlcv[-1][ticker]["close"]
            current_open = ohlcv[-1][ticker]["open"]
            
            # 2. Compute ATR% (Normalized Volatility)
            # As per Section 3: (14-day ATR / Open) lagged by one period
            # We use the previous period's ATR and Open to avoid lookahead bias
            prev_atr = atr_values[-2]
            prev_open = ohlcv[-2][ticker]["open"]
            
            if prev_open == 0:
                continue
                
            atr_percent = prev_atr / prev_open
            
            # 3. Entry Logic
            # - Price is below the lower Bollinger Band (Oversold)
            # - Price is above the 50 SMA (Long-term trend is up)
            # - ATR% is not extreme (Avoiding 'falling knives' in high volatility)
            
            is_oversold = current_price < bb_data["lower"][-1]
            is_uptrend = current_price > sma_fast[-1]
            vol_is_stable = atr_percent < 0.03 # Threshold for "stable" daily volatility
            
            if is_oversold and is_uptrend and vol_is_stable:
                log(f"Entry signal for {ticker} | ATR%: {round(atr_percent*100, 2)}%")
                # Allocation split equally among signaled tickers
                allocation_dict[ticker] = 1 / len(self.tickers)
                
            # 4. Stop Width Calculation (Section 3)
            # stop width = stop_atr_multiplier × ATR% × (intraday open / entry)
            # Here we simulate the logic to check if existing holdings should be cut.
            # Note: Surmount handles executions, but we can reduce allocation to 0 to exit.
            
            holdings = data.get("holdings", {})
            if holdings.get(ticker, 0) > 0:
                stop_atr_multiplier = 2.0
                # Using current_open as the "intraday open" reference
                stop_width = stop_atr_multiplier * atr_percent * current_open
                
                # If price drops more than the stop width from the period open, exit
                if current_price < (current_open - stop_width):
                    log(f"Stop Loss triggered for {ticker}")
                    allocation_dict[ticker] = 0
                else:
                    # Maintain position if no stop triggered
                    allocation_dict[ticker] = 1 / len(self.tickers)

        return TargetAllocation(allocation_dict)