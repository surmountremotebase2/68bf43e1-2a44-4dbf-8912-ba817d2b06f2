from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime
import pandas as pd
import numpy as np

class TradingStrategy(Strategy):

   def __init__(self):
      self.tickers = ["INTC", "TMO", "AMAT", "MMM", "ASML", "NVDA", "LRCX", "ILMN", "TSM", "AMD", "MU", "NXPI", "JNJ", "PFE", "MRK", "GILD", "ABBV", "BMY", "REGN", "AMGN", "FSLR", "SPWR", "ENPH", "SEDG", "BLDP"]
      self.weights = [0.065, 0.065, 0.065, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.020, 0.020, 0.020, 0.020, 0.020]
      self.equal_weighting = False
      self.mrkt = ["QQQ"]
      self.count = 5

   @property
   def interval(self):
      return "1day"

   @property
   def assets(self):
      return self.tickers + self.mrkt

   def realized_volatility_daily(self, series_log_return):
      """
      Get the daily realized volatility which is calculated as the square root
      of sum of squares of log returns within a specific window interval 
      """
      n = len(series_log_return)
      vola =  np.sqrt(np.sum(series_log_return**2)/(n - 1))
      return vola

   def run(self, data):
      self.count -= 1
      today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
      yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')

      allocation_dict = {}
      spy_data = [entry['QQQ']['close'] for entry in data['ohlcv'] if 'QQQ' in entry]
      spy_data = pd.DataFrame(spy_data, columns=['close'])
      spy_data['log_returns'] = np.log(spy_data.close/spy_data.close.shift(1))
      spy_data = spy_data.fillna(0)
      INTERVAL_WINDOW = 60
      n_future = 20

      if today.day == 14 or (today.day > 14 and yesterday.day < 14):
         if self.equal_weighting: 
            allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
         else:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}

      if len(spy_data) > n_future:
         # GET BACKWARD LOOKING REALIZED VOLATILITY
         spy_data['vol_current'] = spy_data.log_returns.rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
         spy_data['vol_current'] = spy_data['vol_current'].bfill()
         # GET FORWARD LOOKING REALIZED VOLATILITY 
         spy_data['vol_future'] = spy_data.log_returns.shift(n_future).fillna(0).rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
         spy_data['vol_future'] = spy_data['vol_future'].bfill()
         volaT = np.percentile(spy_data['vol_current'], 50)
         volaH = np.percentile(spy_data['vol_current'], 80)

         if (spy_data['vol_current'].iloc[-1] > spy_data['vol_future'].iloc[-1] and spy_data['vol_current'].iloc[-1] > volaT):
            
            if spy_data['vol_current'].iloc[-1] > volaH:
               self.count = 20
            else:
               self.count = 15
            allocation_dict = {ticker: 0 for ticker in self.tickers}
            return TargetAllocation(allocation_dict)
         elif self.count < 1:
            #allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
            return TargetAllocation(allocation_dict)
         else:
            allocation_dict = {ticker: 0 for ticker in self.tickers}
            return TargetAllocation(allocation_dict)

      else:
         return TargetAllocation(allocation_dict)
      
      
         return TargetAllocation(allocation_dict)
      return None