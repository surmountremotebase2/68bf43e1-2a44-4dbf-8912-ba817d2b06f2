from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime

class TradingStrategy(Strategy):

   def __init__(self):
      self.tickers = ["INTC", "TMO", "AMAT", "MMM", "ASML", "NVDA", "LRCX", "ILMN", "TSM", "AMD", "MU", "NXPI", "JNJ", "PFE", "MRK", "GILD", "ABBV", "BMY", "REGN", "AMGN", "FSLR", "SPWR", "ENPH", "SEDG", "BLDP"]
      self.weights = [0.065, 0.065, 0.065, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.040, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.035, 0.020, 0.020, 0.020, 0.020, 0.020]
      self.equal_weighting = False

   @property
   def interval(self):
      return "1day"

   @property
   def assets(self):
      return self.tickers

   def run(self, data):
      today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
      yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')
      
      if today.day == 14 or (today.day > 14 and yesterday.day < 14):
         if self.equal_weighting: 
            allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
         else:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))}
         return TargetAllocation(allocation_dict)
      return None