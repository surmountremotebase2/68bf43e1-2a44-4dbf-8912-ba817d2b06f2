from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA, RSI
from surmount.logging import log
from datetime import datetime, timedelta
import numpy as np

class TradingStrategy(Strategy):
    def __init__(self):
        self.assets_list = [
            "QQQ", "XLK", "XLE", "IWD", "XLV", "XLU", "XLP", "IJT", "GLD", "UUP", "SPY", "BIL", "NVDA", "AAPL", "MSFT"
        ]
        self.current_allocation = {asset: 0 for asset in self.assets_list}
        self.data_list = []
        self.count = 0  # Initialize counter for 5-day rebalancing

    @property
    def assets(self):
        return self.assets_list

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        ohlcv = data["ohlcv"]
        
        # Increment counter
        self.count = (self.count + 1) % 10
        
        # Check if there is enough historical data (at least ~1 year)
        if len(ohlcv) < 1:
            return TargetAllocation(self.current_allocation)

        # Only rebalance every 5th day
        if self.count != 0:
            return TargetAllocation(self.current_allocation)

        # Calculate past date (52 weeks ago)
        today_str = ohlcv[-1]["SPY"]["date"]
        today = datetime.strptime(today_str, "%Y-%m-%d %H:%M:%S")  # Updated format to handle timestamp
        past_date = today - timedelta(days=15)
        lpast_date = today - timedelta(days=82)

        # Find the index of the most recent trading day on or before past_date
        for i in range(len(ohlcv)-1, -1, -1):
            date_str = ohlcv[i]["SPY"]["date"]
            date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")  # Updated format
            if date_obj <= past_date:
                past_index = i
                break
        else:
            past_index = 0  # Use the earliest available data if no match
        

        # Calculate SPY and BIL returns
        try:
            spy_close_today = ohlcv[-1]["SPY"]["close"]
            spy_close_past = ohlcv[past_index]["SPY"]["close"]
            spy_close_lpast = ohlcv[-82]["SPY"]["close"]
            spy_ret = (spy_close_today / spy_close_past) - 1
            spy_lret = (spy_close_today / spy_close_lpast) - 1
            spy_ret = spy_lret - spy_ret


            bil_close_today = ohlcv[-1]["BIL"]["close"]
            bil_close_past = ohlcv[past_index]["BIL"]["close"]
            bil_close_lpast = ohlcv[-82]["BIL"]["close"]
            bil_ret = (bil_close_today / bil_close_past) - 1
            bil_lret = (bil_close_today / bil_close_lpast) - 1
            bil_ret = bil_lret - bil_ret

        except KeyError:
            return TargetAllocation(self.current_allocation)  # Handle missing data

        if spy_ret > bil_ret:
            # Bullish market: Allocate to top-performing sector ETFs
            sector_returns = {}
            sectors = ["QQQ", "XLK", "NVDA", "MSFT", "AAPL", "XLE", "XLV", "IJT"]
            for sector in sectors:
                try:
                    close_today = ohlcv[-1][sector]["close"]
                    close_past = ohlcv[past_index][sector]["close"]
                    close_lpast = ohlcv[-82][sector]["close"]
                    ret = (close_today / close_past) - 1
                    lret = (close_today / close_lpast) - 1
                    ret = lret - ret
                    sector_returns[sector] = ret
                except KeyError:
                    continue  # Skip if data is missing for a sector

            # Select top 4 sectors (or all if fewer than 4 are available)
            if len(sector_returns) >= 2:
                top_sectors = sorted(sector_returns, key=sector_returns.get, reverse=True)[:2]
                allocation = {s: 0.5 for s in top_sectors}
            else:
                allocation = {s: 1 / len(sector_returns) for s in sector_returns}
        else:
            # Bearish market: Allocate to safe assets (GLD and UUP)
            allocation = {asset: 0 for asset in self.assets_list}
            allocation = {"GLD": 0.3, "BIL": 0.7}

        # Update current allocation
        self.current_allocation = {asset: 0 for asset in self.assets_list}
        for asset, weight in allocation.items():
            self.current_allocation[asset] = weight

        return TargetAllocation(self.current_allocation)