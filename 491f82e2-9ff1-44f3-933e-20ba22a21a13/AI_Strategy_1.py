from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI, Momentum
from surmount.data import Asset

class DualMomentumInOut(Strategy):
    def __init__(self):
        self.assets = ["TQQQ", "UVXY", "QQQ", "TLT", "UUP", "IEF", "SHY", "GLD", "BSV", "DBC", "REZ", "USMV", "SPHD", "VDC", "XLI", "XLU", "SLV", "DBB"]
        self.interval = "1day"
        self.RSI_PERIOD = 10
        self.MKT = "QQQ"
        self.RISK_OFF_ASSETS = ["TLT", "UUP", "IEF", "SHY", "GLD", "BSV", "DBC", "REZ", "TLT"]
        self.BULLISH_ASSET = "QQQ"
        self.SAFE_ASSET_SELECTION_PERIOD = 120

    @property
    def data(self):
        return []

    def select_momentum_safe_asset(self, data):
        momentum_scores = {}
        for asset in self.RISK_OFF_ASSETS:
            asset_data = data["ohlcv"][asset][-self.SAFE_ASSET_SELECTION_PERIOD:]  # Get the last X days
            momentum = Momentum(asset, asset_data, self.SAFE_ASSET_SELECTION_PERIOD)[-1]
            momentum_scores[asset] = momentum
        return max(momentum_scores, key=momentum_scores.get)

    def run(self, data):
        allocation = {}
        
        rsi_tqqq = RSI("TQQQ", data["ohlcv"]["TQQQ"], self.RSI_PERIOD)[-1]
        rsi_qqq = RSI("QQQ", data["ohlcv"]["QQQ"], self.RSI_PERIOD)[-1]

        # RSI logic can be expanded or adjusted according to strategy needs
        if rsi_tqqq >= 85:
            allocation["UVXY"] = 1  # Full allocation to protective asset
        elif rsi_tqqq <= 20:
            allocation["TQQQ"] = 1  # Full allocation to high-beta asset
        else:
            # Select safe asset based on momentum for risky market condition
            safe_asset = self.select_momentum_safe_asset(data)
            allocation[safe_asset] = 1
        
        # Normalize allocations if necessary
        total_allocation = sum(allocation.values())
        if total_allocation > 1:
            # Adjust allocations to ensure they sum up to 1 or below
            for asset in allocation:
                allocation[asset] /= total_allocation
        
        return TargetAllocation(allocation)