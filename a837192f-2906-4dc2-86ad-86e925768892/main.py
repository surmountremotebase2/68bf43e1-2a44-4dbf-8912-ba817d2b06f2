from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from surmount.technical_indicators import SMA, BB, RSI, EMA
from datetime import datetime
import pandas as pd
import numpy as np


class TradingStrategy(Strategy):

   def __init__(self):
      self.tickers = ["NFLX", "GOOGL", "AAPL", "AMZN", "META"]
      # self.data_list = [InstitutionalOwnership(i) for i in self.tickers]
      #self.data_list = [InsiderTrading(i) for i in self.tickers]
      self.mrkt = "QQQ"
      self.count = 5


   @property
   def interval(self):
      return "1day"

   @property
   def assets(self):
      return self.tickers + [self.mrkt]


   def realized_volatility_daily(self, series_log_return):
      """
      Get the daily realized volatility which is calculated as the square root
      of sum of squares of log returns within a specific window interval 
      """
      n = len(series_log_return)
      vola =  np.sqrt(np.sum(series_log_return**2)/(n - 1))
      return vola


   def run(self, data):
      
      if len(data) > 0:
         today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
         yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')
         self.count -= 1
         allocation_dict = {ticker: 0 for ticker in self.tickers}
         mrktData = [entry[self.mrkt]['close'] for entry in data['ohlcv'] if self.mrkt in entry]
         mrktData = pd.DataFrame(mrktData, columns=['close'])
         mrktData['log_returns'] = np.log(mrktData.close/mrktData.close.shift(1))
         mrktData = mrktData.fillna(0)
         INTERVAL_WINDOW = 60
         n_future = 20

         if len(mrktData) > n_future:
            # GET BACKWARD LOOKING REALIZED VOLATILITY
            mrktData['vol_current'] = mrktData.log_returns.rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
            mrktData['vol_current'] = mrktData['vol_current'].bfill()
            # GET FORWARD LOOKING REALIZED VOLATILITY 
            mrktData['vol_future'] = mrktData.log_returns.shift(n_future).fillna(0).rolling(window=INTERVAL_WINDOW).apply(self.realized_volatility_daily)
            mrktData['vol_future'] = mrktData['vol_future'].bfill()
            volaT = np.percentile(mrktData['vol_current'], 55)
            volaH = np.percentile(mrktData['vol_current'], 80)
            mrktEMA = EMA(self.mrkt, data["ohlcv"], length=200)
            mrktClose = mrktData.close.iloc[-1]

            if (mrktData['vol_current'].iloc[-1] > mrktData['vol_future'].iloc[-1] and mrktData['vol_current'].iloc[-1] > volaT):
               if mrktData['vol_current'].iloc[-1] > volaH:
                  self.count = 5
               else:
                  self.count = 3
               allocation_dict = {ticker: -.1 for ticker in self.tickers}

            elif self.count < 1 and mrktClose > mrktEMA[-2]:
               allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
               #for i in self.data_list:
                  #if tuple(i)[0]=="insider_trading":
                     #if data[tuple(i)] and len(data[tuple(i)])>0:
                        #sales = len([item for item in data[tuple(i)][-20:] if "Sale" in item['transactionType']])
                        #if sales/20 > 0.4:
                           #allocation_dict[tuple(i)[1]] = 0
            else:
               allocation_dict = {ticker: 0 for ticker in self.tickers}

         return TargetAllocation(allocation_dict)
      
      else:
         return None