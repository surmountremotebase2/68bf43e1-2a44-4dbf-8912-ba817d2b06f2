from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime

class TradingStrategy(Strategy):

   def __init__(self):
      self.tickers = ["NVDA", "AMD", "GOOGL", "MSFT", "AMZN", "IBM", "INTC", "MU", "QCOM", "TXN", "AVGO", "AMAT", "NXPI", "SWKS", "LRCX", "ADI", "KLAC", "MRVL", "CDNS", "SNPS", "PANW", "FTNT", "CHKP", "OKTA", "NET", "NOW", "AVGO", "DOCU", "TEAM", "TWLO"]
      self.weights = [0.08, 0.08, 0.07, 0.07, 0.06, 0.06, 0.06, 0.05, 0.05, 0.03, 0.03, 0.03, 0.025, 0.025, 0.02, 0.02, 0.015, 0.015, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
      self.equal_weighting = False
      self.counter = 0

   @property
   def interval(self):
      return "1day"

   @property
   def assets(self):
      return self.tickers

   def run(self, data):
      if len(data['ohlcv']) < 2:
         self.counter += 1
         if self.counter >= 30:
            self.counter = 0
            if self.equal_weighting: 
               allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
            else:
               allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))} 
            return TargetAllocation(allocation_dict)
         else:
            return None

      today = datetime.strptime(str(next(iter(data['ohlcv'][-1].values()))['date']), '%Y-%m-%d %H:%M:%S')
      yesterday = datetime.strptime(str(next(iter(data['ohlcv'][-2].values()))['date']), '%Y-%m-%d %H:%M:%S')
      
      if today.day == 12 or (today.day > 12 and yesterday.day < 12):
         if self.equal_weighting: 
            allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
         else:
            allocation_dict = {self.tickers[i]: self.weights[i] for i in range(len(self.tickers))} 
         return TargetAllocation(allocation_dict)
      return None