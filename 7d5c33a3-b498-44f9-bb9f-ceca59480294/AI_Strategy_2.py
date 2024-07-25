from surmount.base_class import Strategy, TargetAllocation
from surmount.data import OHLCV
from datetime import datetime, timedelta

class TradingStrategy(Strategy):
    def __init__(self):
        # Define a broad list of ticker symbols to consider for the strategy.
        # This example uses a fictional, limited list for demonstration.
        self.tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "FB", "TSLA", "BRK.A", "JNJ", "V", "PG"]
        # Initialize the data list with OHLCV data for each ticker.
        self.data_list = [OHLCV(i) for i in self.tickers]

    @property
    def interval(self):
        # Set the data interval to "1day" for daily historical data analysis.
        return "1day"

    @property
    def assets(self):
        # Specify the assets this strategy will operate on - the list of tickers.
        return self.tickers

    @property
    def data(self):
        # Provide access to the required data for the strategy.
        return self.data_list

    def run(self, data):
        performance = {}
        today = datetime.now()
        six_months_ago = today - timedelta(days=30*6)

        # Calculate performance for each stock
        for ticker in self.tickers:
            ohlcv_data = data[("ohlcv", ticker)]
            if ohlcv_data:
                start_price = None
                end_price = ohlcv_data[-1]['close']  # Most recent price data
                
                # Find the price 6 months ago
                for ohlcv in ohlcv_data:
                    date = datetime.strptime(ohlcv['date'], "%Y-%m-%d")
                    if date <= six_months_ago:
                        start_price = ohlcv['close']

                if not start_price:
                    print(f'Start price not found for {ticker}. Using earliest available closing price.')
                    start_price = ohlcv_data[0]['close']
                
                performance[ticker] = (end_price - start_price) / start_price
        
        allocation_dict = {}
        sorted_performance = sorted(performance.items(), key=lambda x: x[1], reverse=True)
        top_performers = sorted_performance[:max(1, len(sorted_performance)//10)]
        bottom_performers = sorted_performance[-max(1, len(sorted_performance)//10):]
        
        # Allocate investments based on performance, long top performers and short bottom performers
        for ticker, _ in top_performers:
            allocation_dict[ticker] = 1 / len(top_performers)
        for ticker, _ in bottom_performers:
            allocation_dict[ticker] = -1 / len(bottom_performers)
        
        # Normalize allocations to ensure they sum up to 1 or -1 for long and short positions respectively
        long_alloc = sum([val for val in allocation_dict.values() if val > 0])
        short_alloc = sum([abs(val) for val in allocation_dict.values() if val < 0])
        
        if long_alloc > 0:
            for ticker in [t[0] for t in top_performers]:
                allocation_dict[ticker] /= long_alloc
        
        if short_alloc > 0:
            for ticker in [t[0] for t in bottom_performers]:
                allocation_dict[ticker] /= -short_alloc

        return TargetAllocation(allocation_dict)