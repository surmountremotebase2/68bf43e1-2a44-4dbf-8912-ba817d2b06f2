from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime
import pandas as pd

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

    def realized_volatility_daily(series_log_return):
        """
        Get the daily realized volatility which is calculated as the square root
        of sum of squares of log returns within a specific window interval 
        """
        n = len(series_log_return)
        return np.sqrt(np.sum(series_log_return**2)/(n - 1))        


    def run(self, data):
        self.count += 7
        spy_data = [entry['SPY'] for entry in data['ohlcv'] if 'SPY' in entry]
        spy_data = pd.DataFrame(spy_data.Close, index=spy_data.date)
        df['returns'] = 100 * spy_data.Close.pct_change().dropna()
        # CALCULATE LOG RETURNS BASED ON ABOVE FORMULA
        df['log_returns'] = np.log(spy_data.Close/spy_data.Close.shift(1))
                
        INTERVAL_WINDOW = 30
        n_future = 7

        # GET BACKWARD LOOKING REALIZED VOLATILITY
        df['vol_current'] = df.log_returns.rolling(window=INTERVAL_WINDOW)\
                                        .apply(realized_volatility_daily)

        # GET FORWARD LOOKING REALIZED VOLATILITY 
        df['vol_future'] = df.log_returns.shift(-n_future)\
                                        .rolling(window=INTERVAL_WINDOW)\
                                        .apply(realized_volatility_daily)
                                        

        # Check if the current ATR or Realized Volatility is above the 7th or 8th decile
        if spy_data['ATR'].iloc[-1] > atr_deciles[1] or spy_data['Realized Volatility'].iloc[-1] > vol_deciles[1]:
            log.info("Switching to cash allocation due to high volatility")
            return TargetAllocation({ticker: 0 for ticker in self.tickers})
        else:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
            return TargetAllocation(allocation_dict)

        if self.count % 7 == 0:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
            return TargetAllocation(allocation_dict)
        return None