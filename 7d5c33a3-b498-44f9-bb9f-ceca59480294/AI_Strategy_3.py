from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI, EMA
from surmount.data import SectorPerformance
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        self.sectors = [
            "XLY",  # Consumer Discretionary
            "XLP",  # Consumer Staples
            "XLE",  # Energy
            "XLF",  # Financials
            "XLV",  # Health Care
            "XLI",  # Industrials
            "XLB",  # Materials
            "XLRE", # Real Estate
            "XLK",  # Technology
            "XLU",  # Utilities
        ]
        self.data_list = [SectorPerformance(i) for i in self.sectors]

    @property
    def interval(self):
        return "1week"  # Adjusting the investment on a weekly basis

    @property
    def assets(self):
        return self.sectors

    @property
    def data(self):
        return self.data_list

    def run(self, data):
        # Calculate the Relative Strength Index (RSI) for each sector
        sector_strength = {}
        for sector in self.sectors:
            rsi_value = RDI(sector, data["ohlcv"], 14)  # 14 periods for RSI
            if rsi_value:
                sector_strength[sector] = rsi_value[-1]  # Take the last value
            else:
                sector_strength[sector] = None
        
        # Filtering the sectors with the highest RSI values indicating strength
        strong_sectors = dict(sorted(sector_strength.items(), 
                                     key=lambda item: item[1] if item[1] is not None else 0, 
                                     reverse=True)[:3])  # Top 3 sectors

        allocation_dict = {}
        if strong_sectors:
            # Allocate equally among the top 3 sectors
            allocation_value = 1.0 / len(strong_sectors) if strong_sectors else 0
            for sector in self.sectors:
                allocation_dict[sector] = allocation_value if sector in strong_sectors else 0
        else:
            # Allocate equally among all sectors if we can't determine the strength
            allocation_value = 1.0 / len(self.sectors)
            for sector in self.sectors:
                allocation_dict[sector] = allocation_value

        return TargetAllocation(allocation_dict)