from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime
import pandas as pd
import numpy as np

class TradingStrategy(Strategy):

    def __init__(self):
        self.tickers = [
            "AMZN", "AAPL", "META", "GOOGL", "MSFT", "NVDA", "PYPL", "SHOP",
            "SQ", "TSLA", "TTD", "ADBE", "ATVI", "NFLX", "TWLO", "ZM", "ROKU",
            "PTON", "SNAP", "SE", "SPOT", "PINS", "UBER", "LYFT", "DOCU", "ETSY",
            "ZG", "W", "CHWY", "CRWD"
        ]
        self.bench = ["SPY"]
        self.weights = [
            0.045, 0.045, 0.045, 0.045, 0.045, 0.035, 0.035, 0.035,
            0.035, 0.035, 0.03, 0.03, 0.03, 0.03, 0.025, 0.025, 0.025,
            0.025, 0.025, 0.02, 0.02, 0.02, 0.02, 0.02, 0.015, 0.015,
            0.015, 0.015, 0.015, 0.015
        ]
        self.count = 0

    @property
    def interval(self):
        return "1day"

    @property
    def assets(self):
        return self.tickers + self.bench

    def realized_volatility_daily(self, series_log_return):
        """
        Get the daily realized volatility which is calculated as the square root
        of sum of squares of log returns within a specific window interval 
        """
        n = len(series_log_return)
        vola =  np.sqrt(np.sum(series_log_return**2)/(n - 1))
        return vola
        #return series_log_return.rolling(window=252).std() * np.sqrt(252)       


    def run(self, data):
        self.count += 7
        spy_data = [entry['SPY']['close'] for entry in data['ohlcv'] if 'SPY' in entry]
        spy_dates = [entry['SPY']['date'] for entry in data['ohlcv'] if 'SPY' in entry]
        spy_data = pd.DataFrame(spy_data, columns=['close'])
        spy_data['returns'] = 100 * spy_data.close.pct_change().dropna()
        # CALCULATE LOG RETURNS BASED ON ABOVE FORMULA
        spy_data['log_returns'] = np.log(spy_data.close/spy_data.close.shift(1))
        spy_data = spy_data.fillna(0)
        INTERVAL_WINDOW = 30
        n_future = 7

        if len(spy_data) > n_future:

            #log(f"{spy_data['log_returns'].iloc[-1]}")
            # GET BACKWARD LOOKING REALIZED VOLATILITY
            spy_data['vol_current'] = spy_data.log_returns.rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
            #log(f"{spy_data['vol_current'].iloc[-1]}")

            # GET FORWARD LOOKING REALIZED VOLATILITY 
            spy_data['vol_future'] = spy_data.log_returns.shift(n_future).fillna(0).rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
                                            
            #log(f"{spy_data['vol_future'].iloc[-1]}")
            

            #if self.count % 7 == 0:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}

                # Check if the current ATR or Realized Volatility is above the 7th or 8th decile
            if spy_data['vol_current'].iloc[-1] > spy_data['vol_future'].iloc[-1]:
                #log(f"Switching to cash allocation due to high volatility")
                return TargetAllocation({ticker: 0 for ticker in self.tickers})
            else:
                #log(f"Switching to cash allocation due to high volatility")
                allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
                return TargetAllocation(allocation_dict)

        return TargetAllocation({ticker: 0 for ticker in self.tickers})
            return TargetAllocation(allocation_dict)
        return None