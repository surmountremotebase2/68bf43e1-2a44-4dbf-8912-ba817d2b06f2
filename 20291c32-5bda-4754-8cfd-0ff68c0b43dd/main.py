from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import RSI
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # Define the ticker symbol for the asset we're interested in
        self.tickers = ["TECL"]
        self.bull = 0

    @property
    def assets(self):
        # Specify which assets this strategy applies to
        return self.tickers

    @property
    def interval(self):
        # Define the time interval for the RSI calculation
        # Using "1day" for daily RSI. Highly frequent intervals like 1min may lead to higher transaction costs.
        return "1day"

    def run(self, data):
        # Initialize the target allocation. By default, hold no position.
        allocation_dict = {"TECL": 0}

        # Calculate the RSI for TECL
        rsi_values = RSI("TECL", data["ohlcv"], length=10)  # Default length for RSI is 14 days

        # Check if we have enough data to compute the RSI
        if rsi_values and len(rsi_values) > 0:
            current_rsi = rsi_values[-1]  # Get the most recent RSI value

            #log(f"Current RSI value for TECL: {current_rsi}")

            # Buy (take a long position) if RSI is below 30 (oversold)
            if current_rsi < 25:
                allocation_dict["TECL"] = 1  # Set allocation to 100%
                self.bull = 1
                #log("RSI is oversold. Going long on TECL.")
            # Sell (take no position) if RSI is above 70 (overbought)
            elif current_rsi > 40:
                allocation_dict["TECL"] = 0  # Hold no position
                self.bull = 0
                #log("RSI is overbought. Exiting position in TECL.")
            else:
                if self.bull == 1:
                    allocation_dict["TECL"] = 1
                else:
                    allocation_dict["TECL"] = 0
                # For RSI values between 30 and 70, hold the current position
                # This example assumes exiting the position, equivalent to 'allocation_dict["TECL"] = 0'
                # Adjust according to your strategy (e.g., maintain previous position)
                #log("RSI is neutral. Holding current position.")
        else:
            log("Not enough data to calculate RSI.")

        # Return the target allocation
        return TargetAllocation(allocation_dict)