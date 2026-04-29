from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB, ATR, EMA
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Focus tickers for the strategy
        self.tickers = ["SPY", "QQQ", "XLK", "SMH", "GLD"]
        self.data_list = []

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Using 1day ensures the EMA length of 200 perfectly matches 200 trading days.
        return "1day"

    def run(self, data):
        ohlcv = data["ohlcv"]
        allocation_dict = {ticker: 0 for ticker in self.tickers}
        
        # Minimum data requirement increased to 201 periods to calculate the 200 EMA
        if len(ohlcv) < 201:
            return TargetAllocation(allocation_dict)

        for ticker in self.tickers:
            # 1. Compute Technical Indicators
            bb_data = BB(ticker, ohlcv, 20, 2)
            atr_values = ATR(ticker, ohlcv, 14)
            
            # --- CHANGED: Market filter is now a 200 EMA ---
            ema_market = EMA(ticker, ohlcv, 100)
            
            if bb_data is None or atr_values is None or ema_market is None:
                continue

            current_price = ohlcv[-1][ticker]["close"]
            current_open = ohlcv[-1][ticker]["open"]
            
            # 2. Compute ATR% (Normalized Volatility)
            # (14-day ATR / Open) lagged by one period
            prev_atr = atr_values[-2]
            prev_open = ohlcv[-2][ticker]["open"]
            
            if prev_open == 0:
                continue
                
            atr_percent = prev_atr / prev_open
            
            # 3. Entry Logic
            # - Price is below the lower Bollinger Band (Oversold)
            # - Price is above the 200 EMA (Long-term market trend is up)
            # - ATR% is stable
            is_oversold = current_price < bb_data["lower"][-1]
            is_uptrend = current_price > ema_market[-1]
            vol_is_stable = atr_percent < 0.03 
            
            if is_oversold and is_uptrend and vol_is_stable:
                log(f"Entry signal for {ticker} | ATR%: {round(atr_percent*100, 2)}%")
                allocation_dict[ticker] = 1 / len(self.tickers)
                
            # 4. Stop Width Calculation
            # stop width = stop_atr_multiplier × ATR% × (intraday open)
            holdings = data.get("holdings", {})
            if holdings.get(ticker, 0) > 0:
                stop_atr_multiplier = 2.0
                stop_width = stop_atr_multiplier * atr_percent * current_open
                
                # If price drops more than the stop width from the period open, exit
                if current_price < (current_open - stop_width):
                    log(f"Stop Loss triggered for {ticker}")
                    allocation_dict[ticker] = 0
                else:
                    # Maintain position if no stop triggered
                    allocation_dict[ticker] = 1 / len(self.tickers)

        return TargetAllocation(allocation_dict)