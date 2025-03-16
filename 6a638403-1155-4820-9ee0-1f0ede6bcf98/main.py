from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI, SMA
from surmount.data import FinancialStatement, Ratios, ohlcv

class TradingStrategy(Strategy):
    def __init__(self):
        # Tickers for the strategy
        self.growth_stocks = ["TSLA"]
        self.defensive_stocks = ["PLUG", "ENPH"]
        self.sectors_etf = ["ICLN"]

        # Additional data sources
        self.financial_data = []  # Placeholder for industry P/B data
        for ticker in self.growth_stocks + self.defensive_stocks:
            self.financial_data.append(Ratios(ticker))
            self.financial_data.append(FinancialStatement(ticker))
        
        # Initializing other attributes
        self.stop_loss_tickers = []

    @property
    def interval(self):
        return "1day"
    
    @property
    def assets(self):
        return self.growth_stocks + self.defensive_stocks + self.sectors_etf + self.stop_loss_tickers
    
    @property
    def data(self):
        return self.financial_data
    
    def run(self, data):
        allocation_dict = {}
        total_assets = len(self.growth_stocks + self.defensive_stocks + self.sectors_etf) - len(self.stop_loss_tickers)
        base_allocation = 1 / total_assets if total_assets else 0

        # Apply Mean Reversion and P/B Rebalancing Rule
        for in self.growth_stocks + self.defensive_stocks:
            historical_data = ohlcv[ticker]['close']
            current_price = historical_data[-1]
            previous_quarter_price = historical_data[-60]  # Assuming 60 trading days in a quarter

            # Mean Reversion Strategy
            if ticker in self.defensive_stocks and previous_quarter_price / current_price - 1 > 0.20:
                allocation_dict[ticker] = base_allocation * 1.5  # Increase position
            elif ticker == "TSLA":
                # TSLA RSI Take profits
                rsi_val = RSI(ticker, historical_data, 14)
                if rsi_val[-1] > 85:
                    allocation_dict[ticker] = 0  # Take profit, no allocation
                    
            # Checking for stop-loss - If a stock falls below its 200-day MA, remove it
            ma_200 = SMA(ticker, historical_data, 200)
            if current_price < ma_200[-1]:
                allocation_dict[ticker] = 0  # Stop loss triggered
                self.stop_loss_tickers.append(ticker)  # Add to stop loss list to avoid future allocation
            else:
                # Applying base allocation if not increased or stopped loss
                if ticker not in allocation_dict:
                    allocation_dict[ticker] = base_allocation
            
        # Sector Trend Rule
        icln_data = ohlcv["ICLN"]['close']
        current_icln_price = icln_data[-1]
        previous_month_icln_price = icln_data[-20]  # Assuming 20 trading days in a month
        if current_icln / previous_month_icln_price - 1 > 0.10:
            # Increase Clean Energy ETF (ICLN) Exposure - Doubling its weight
            allocation_dict["ICLN"] = base_allocation * 2
        elif "ICLN" not in allocation_dict:
            # Normal allocation for ICLN if no specific trend rule applies
            allocation_dict["ICLN"] = base_allocation

        return TargetAllocation(allocation_dict)