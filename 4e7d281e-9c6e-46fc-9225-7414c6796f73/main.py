from surmount.base_class import Strategy, TargetAllocation
from surmount.data import (
    TopActiveStocks, TopCongressTraders, TopGovernmentContracts,
    TopLobbyingContracts, MedianCPI,
    StickyPriceConsumerPriceIndex)
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Initialize data sources
        self.data_list = [
            TopActiveStocks(),
            TopCongressTraders(),
            TopGovernmentContracts(),
            TopLobbyingContracts(),
            MedianCPI(),
            StickyPriceConsumerPriceIndex()
        ]
        self.tickers = []  # Will be populated dynamically

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
        
        # Get top active stocks
        active_stocks = data[("top_active_stocks",)]    
        tickers = [stock["ticker"] for stock in active_stocks]
        log(f"TICKERS: {tickers}")
             
        # Get latest data points
        gov_contracts = data[("top_government_contracts",)]
        lobbying_contracts = data[("top_lobbying_contracts",)]
        median_cpi = data[("median_cpi",)]
        sticky_cpi = data[("sticky_price_consumer_price_index",)]

        contract_tickers = set()
        if gov_contracts and len(gov_contracts) > 0:
            contracts_top_20 = gov_contracts
            contract_tickers = {contract["ticker"] for contract in contracts_top_20 
                              if contract["ticker"] in tickers and contract["amount"] > 1000000}  # $1M threshold

        lobbying_tickers = set()
        if lobbying_contracts and len(lobbying_contracts) > 0:
            lobbying_top_20 = lobbying_contracts
            lobbying_tickers = {contract["ticker"] for contract in lobbying_top_20 
                              if contract["ticker"] in tickers and contract["amount"] > 1000000}  # $1M threshold

        # Direct inflation analysis using MedianCPI
        inflation_score = 0
        if len(median_cpi) > 1 and len(sticky_cpi) > 1:
            # Get direct month-over-month change in MedianCPI
            median_cpi_change = median_cpi[-1]["value"] - median_cpi[-2]["value"]
            sticky_cpi_change = sticky_cpi[-1]["value"] - sticky_cpi[-2]["value"]
            
            # Score based on MedianCPI change
            if median_cpi_change <= -0.2:  # Strong decrease
                inflation_score = 1.0
            elif median_cpi_change <= -0.1:  # Moderate decrease
                inflation_score = 0.8
            elif median_cpi_change <= 0:  # Mild decrease
                inflation_score = 0.6
            elif median_cpi_change <= 0.1:  # Mild increase
                inflation_score = 0.4
            elif median_cpi_change <= 0.2:  # Moderate increase
                inflation_score = 0.2
            else:  # Strong increase
                inflation_score = 0

            # Adjust score based on sticky CPI
            if sticky_cpi_change > 0:
                inflation_score *= 0.8  # Reduce score if sticky prices are rising

        # Calculate raw scores first
        scores = {}
        total_score = 0
        for ticker in tickers:
            score = 0
            
            # Base weights
            if ticker in contract_tickers:
                score += 0.35  # 35% weight for government contracts
            if ticker in lobbying_tickers:
                score += 0.40  # 40% weight for lobbying activity
            
            # Apply inflation score
            inflation_weight = 0.25  # 25% weight for inflation conditions
            score += inflation_weight * inflation_score

            scores[ticker] = score
            total_score += score

        # Normalize allocations to sum to 1
        if total_score > 0:
            for ticker in tickers:
                allocation_dict[ticker] = scores[ticker] / total_score
        else:
            # If no signals, equal weight allocation
            weight = 1.0 / len(tickers) if tickers else 0
            for ticker in tickers:
                allocation_dict[ticker] = weight

        print(f"Final allocations: {allocation_dict}")
        print(f"MedianCPI change: {median_cpi_change if len(median_cpi) > 1 else 'N/A'}")
        print(f"Inflation score: {inflation_score}")
    
        return TargetAllocation(allocation_dict)