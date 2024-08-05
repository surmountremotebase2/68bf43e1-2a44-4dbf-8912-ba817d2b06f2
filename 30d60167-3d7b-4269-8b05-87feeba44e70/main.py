from surmount.base_class import Strategy, TargetAllocation, backtest
from surmount.logging import log
from datetime import datetime

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

    def run(self, data):
        self.count += 7
        
        spy_data = data["SPY"]
        spy_data['TR'] = np.maximum(spy_data['High'] - spy_data['Low'], np.maximum(spy_data['High'] - spy_data['Close'].shift(1), spy_data['Close'].shift(1) - spy_data['Low']))
        spy_data['ATR'] = spy_data['TR'].rolling(window=14).mean()
        spy_data['Returns'] = spy_data['Close'].pct_change()
        spy_data['Realized Volatility'] = spy_data['Returns'].rolling(window=252).std() * np.sqrt(252)

        # Calculate the 7th and 8th deciles
        atr_deciles = np.percentile(spy_data['ATR'].dropna(), [70, 80])
        vol_deciles = np.percentile(spy_data['Realized Volatility'].dropna(), [70, 80])

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