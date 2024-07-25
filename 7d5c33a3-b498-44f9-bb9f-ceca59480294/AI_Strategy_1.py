from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
# Assuming there's a way to fetch financial data or it's manually inserted
from surmount.data import FinancialData

class TradingStrategy(Strategy):
    def __init__(self):
        # Example tickers and their industries
        self.tickers = ["AAPL", "MSFT", "INTC", "AMD"]
        self.industries = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "INTC": "Semiconductors",
            "AMD": "Semiconductors"
        }
        # Assuming FinancialData fetches P/E ratio, otherwise it needs to be provided/manually updated
        self.data_list = [FinancialData(i) for i in self.tickers]
        # Industry average P/E ratios - these would ideally be updated periodically
        self.industry_pe = {
            "Technology": 30,
            "Semiconductors": 20
        }
        # Threshold to consider stock as undervalued
        self.discount_threshold = 0.8  # 20% discount

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
        allocation_dict = {}

        for ticker in self.tickers:
            industry = self.industries[ticker]
            industry_pe_average = self.industry_pe[industry]
            # Assuming data provides the P/E ratio, otherwise needs implementation to fetch this data
            ticker_pe = data[(ticker, "pe_ratio")]

            if ticker_pe < (industry_pe_average * self.discount_threshold):
                # This ticker is considered undervalued; allocate funds to buy
                allocation_dict[ticker] = 1.0 / len(self.tickers)  # Equally weighted for simplicity
            else:
                # This ticker is not considered undervalued; do not allocate funds
                allocation_dict[ticker] = 0.0

        return TargetAllocation(allocation_dict)