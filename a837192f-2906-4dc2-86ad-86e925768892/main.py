from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from surmount.technical_indicators import SMA, BB, RSI
from surmount.data import Asset, InstitutionalOwnership, InsiderTrading

class TradingStrategy(Strategy):

   def __init__(self):
      self.tickers = ["NFLX", "GOOGL", "AAPL", "AMZN", "META"]
      # self.data_list = [InstitutionalOwnership(i) for i in self.tickers]
      self.data_list = [InsiderTrading(i) for i in self.tickers]

   @property
   def interval(self):
      return "1day"

   @property
   def assets(self):
      return self.tickers

   @property
   def data(self):
      return self.data_list

   def run(self, data):
      allocation_dict = {i: 1/len(self.tickers) for i in self.tickers}
      for i in self.data_list:
         if tuple(i)[0]=="insider_trading":
            if data[tuple(i)] and len(data[tuple(i)])>0:
               sales = len([i for i in data[tuple(i)][-20:] if "Sale" in i['transactionType']])
               if sales/20 > 0.4:
                  allocation_dict[tuple(i)[1]] = 0

      return TargetAllocation(allocation_dict)