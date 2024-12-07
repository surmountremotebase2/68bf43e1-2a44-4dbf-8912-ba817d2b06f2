from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import BB
from surmount.logging import log

class TradingStrategy(Strategy):

    @property
    def assets(self):
        # This strategy focuses on NVDA
        return ["NVDA"]

    @property
    def interval(self):
        # Trading based on hourly data
        return "1hour"

    def run(self, data):
        # Initialize zero allocation for NVDA
        nvda_stake = 0

        # Fetch hourly data for NVDA
        data_nvda = data["ohlcv"]["NVDA"]

        if len(data_nvda) >= 20:  # Check if there's enough data for calculation
            # Calculate Bollinger Bands for NVDA
            nvda_bbands = BB("NVDA", [data_nvda], 20, 2)  # Using std deviation of 2 for bands

            # Get the latest close price for NVDA
            current_price = data_nvda[-1]['close']

            # Decision to go long if the close is above the upper Bollinger Band
            if current_price > nvda_bbands['upper'][-1]:
                log("Going long on NVDA")
                nvda_stake = 1  # Going long

            # Decision to go short if the close is below the lower Bollinger Band
            elif current_price < nvda_bbands['lower'][-1]:
                log("Going short on NVDA")
                nvda_stake = -.1  # Short-selling NVDA
            
            # Close position if the close crosses the middle Bollinger Band
            elif nvda_bbands['lower'][-1] < current_price < nvda_bbands['upper'][-1]:
                if data["holdings"]["NVDA"] != 0:  # Check if there's an existing position
                    log("Closing position on NVDA")
                    nvda_stake = 0  # Closing any existing position
            else:
                log("No action for NVDA")

        else:
            log("Not enough data to calculate Bollinger Bands for NVDA")
        
        # Create and return the target allocation object
        # Note: For simplification, short position indicated by negative value
        # In actual trading environment, consider using separate handling for short positions
        return TargetAllocation({"NVDA": nvda_stake})