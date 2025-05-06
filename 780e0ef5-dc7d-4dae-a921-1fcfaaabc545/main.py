from surmount.base_class import Strategy, TargetAllocation
from surmount.data import Asset
from surmount.technical_indicators import RSI
from surmount.logging import log
import numpy as np

class DualMomentumInOut(Strategy):
    def __init__(self):
        # Symbols
        self.symbols = ["TQQQ", "UVXY", "QQQ", "SLV", "GLD", "XLI", "XLU", "DBB", "UUP", "TLT", "IEF", "SHY", "USMV", "SPHD", "VDC", "BSV", "DBC", "REZ", "MEDCPIM158SFRBCLE"]
        
        # Starting variables
        self.bull = True
        self.safe_asset = None
        self.count = 0
        self.outday = 0
        
        # RSI indicators for TQQQ and QQQ
        self.rsi_tqqq = RSI("TQQQ", self.data["ohlcv"], 10)
        self.rsi_qqq = RSI("QQQ", self.data["ohlcv"], 10)

    @property
    def data(self):
        # Specify required data, including MEDCPIM158SFRBCLE for CPI data
        return [Asset(symbol) for symbol in self.symbols]

    @property
    def interval(self):
        # Use daily data for the strategy
        return "1day"
    
    def run(self, data):
        # Implement trading logic here
        
        # Calculate annualized volatility for QQQ
        returns = np.log(data["ohlcv"]["QQQ"]["close"] / data["ohlcv"]["QQQ"]["close"].shift(1))
        volatility = returns.std() * np.sqrt(252)
        
        # Dynamic period and wait_days calculation
        period = max(20, np.floor((1 - volatility) * 85))
        wait_days = np.floor(volatility * 85)
        
        # Compute RSI for TQQQ and QQQ
        rsi_tqqq = self.rsi_tqqq[-1]  # Assuming last value is most recent
        rsi_qqq = self.rsi_qqq[-1]
        
        # Daily Trading Logic
        allocation_dict = self.daily_trading_logic(rsi_tqqq, period, data)
        
        # Diagnostics and visualization code would go here, in a real trading platform
        
        return TargetAllocation(allocation_dict)
    
    def daily_trading_logic(self, rsi_tqqq, period, data):
        allocation = {}
        
        # Implement RSI-based trading rules for TQQQ and UVXY
        if rsi_tqqq >= 85:
            allocation = {"UVXY": 1}  # Full-weight long UVXY
        elif rsi_tqqq <= 80:
            # Exit UVXY position
            allocation = {"UVXY": 0}
        elif rsi_tqqq <= 20:
            # Full-weight long TQQQ
            allocation = {"TQQQ": 1}
        elif rsi_tqqq >= 30:
            # Exit TQQQ position
            allocation = {"TQQQ": 0}
        
        # Add additional trading logic based on Regime rules, Momentum-Based Safe Asset Selection, and Inflation Data
        
        return allocation

# Note to user: Customize the data handling, indicator calculation, and portfolio management logic as necessary.