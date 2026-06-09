from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA, RSI
from surmount.logging import log

class TradingStrategy(Strategy):
    def __init__(self):
        # SVXY provides short-volatility exposure (captures contango)
        # VXX provides long-volatility exposure (used as indicator and hedge)
        self.tickers = ["SVXY", "VXX"]
        
    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        # Daily interval is standard for VIX ETN term structure models
        return "1day"

    @property
    def data(self):
        # Only requires standard OHLCV data
        return []

    def run(self, data):
        ohlcv = data.get("ohlcv", [])
        
        # Define default/empty allocations
        allocation = {"SVXY": 0.0, "VXX": 0.0}
        
        # Data sufficiency check (Requires at least 30 periods for SMA and RSI stabilization)
        if len(ohlcv) < 30:
            log("Insufficient historical data to calculate indicators.")
            return TargetAllocation(allocation)
        
        try:
            # 1. Calculate technical indicators using the long-volatility proxy (VXX)
            vxx_sma = SMA("VXX", ohlcv, length=20)
            vxx_rsi = RSI("VXX", ohlcv, length=14)
            
            # Ensure indicators computed successfully
            if vxx_sma is None or vxx_rsi is None or len(vxx_sma) == 0 or len(vxx_rsi) == 0:
                return TargetAllocation(allocation)
            
            # Fetch the most recent values
            current_vxx_price = ohlcv[-1]["VXX"]["close"]
            latest_sma = vxx_sma[-1]
            latest_rsi = vxx_rsi[-1]
            
            # 2. Implement the Dual Approach Logic
            
            # REGIME 1: Volatility is in a structural downtrend (VXX below its 20-day SMA)
            # This is the ideal environment for capturing the short-volatility premium (Contango).
            if current_vxx_price < latest_sma:
                
                # Check Momentum Filter (RSI) for Dynamic Sizing
                if latest_rsi > 65:
                    # Volatility experienced a minor intraday spike but remains structurally down.
                    # This represents a high-conviction entry point to short volatility.
                    log(r"Regime: Contango | Condition: Volatility Overbought. Increasing SVXY exposure.")
                    allocation["SVXY"] = 0.70
                    allocation["VXX"] = 0.00
                    
                elif latest_rsi < 35:
                    # Volatility is extremely compressed. The risk of an imminent explosive spike is high.
                    # Reduce allocation significantly to protect capital.
                    log("Regime: Contango | Condition: Volatility Compressed. De-risking portfolio.")
                    allocation["SVXY"] = 0.15
                    allocation["VXX"] = 0.00
                    
                else:
                    # Baseline short-volatility allocation under normal contango conditions.
                    log("Regime: Contango | Condition: Normal. Standard short-vol allocation.")
                    allocation["SVXY"] = 0.50
                    allocation["VXX"] = 0.00

            # REGIME 2: Volatility is in a structural uptrend (VXX above its 20-day SMA)
            # This indicates market stress, backwardation, or rising risk-off sentiment.
            else:
                
                # Check Momentum Filter (RSI) for Exhaustion / Tactical Reversal
                if latest_rsi > 75:
                    # Extreme volatility spike. History shows these are highly mean-reverting.
                    # Tactically scale into a minor short-vol position to capture the post-spike crush.
                    log("Regime: Volatility Spike | Condition: Extreme Overbought. Tactical short-vol entry.")
                    allocation["SVXY"] = 0.30
                    allocation["VXX"] = 0.00
                    
                elif latest_rsi < 45:
                    # Volatility has broken out into an uptrend but is currently building energy.
                    # Allocate a small hedge to Long Volatility (VXX).
                    log("Regime: Volatility Uptrend | Condition: Consolidating. Holding long-vol hedge.")
                    allocation["SVXY"] = 0.00
                    allocation["VXX"] = 0.20
                    
                else:
                    # High risk regime. Capital preservation is prioritized; stay flat in cash.
                    log("Regime: Volatility Uptrend | Condition: High Risk. Sitting in cash.")
                    allocation["SVXY"] = 0.00
                    allocation["VXX"] = 0.00
                    
        except Exception as e:
            log(f"Error executing strategy logic: {str(e)}")
            return TargetAllocation({"SVXY": 0.0, "VXX": 0.0})

        # Return final targeted asset allocations securely capped under 1.0
        return TargetAllocation(allocation)