from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA, EMA
from surmount.data import MedianCPI
from surmount.logging import log
import math


class TradingStrategy(Strategy):

    def __init__(self):
        self.tickers = [
            "CWB", "HYG", "TLT", "IEF", "TIP", "SHY", "SPY", "GLD"
        ]
        self.data_list = [MedianCPI()]

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return self.data_list

    # =========================================================
    # Helpers
    # =========================================================

    def closes(self, ohlcv, ticker):
        return [b[ticker]["close"] for b in ohlcv if ticker in b]

    def monthly(self, series):
        return series[::21] if len(series) > 21 else series

    def mom6(self, series):
        lb = 126
        if len(series) < lb + 1:
            return None
        return (series[-1] / series[-lb]) - 1

    def vol20(self, series):
        if len(series) < 22:
            return None

        r = []
        for i in range(-20, 0):
            if series[i - 1] == 0:
                continue
            r.append(series[i] / series[i - 1] - 1)

        if len(r) < 5:
            return None

        mean = sum(r) / len(r)
        var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)

        return math.sqrt(var) * math.sqrt(252)

    # =========================================================
    # MAIN
    # =========================================================

    def run(self, data):

        ohlcv = data["ohlcv"]
        alloc = {t: 0.0 for t in self.tickers}

        log(f"Data availability SPY={len([b for b in ohlcv if 'SPY' in b])} GLD={len([b for b in ohlcv if 'GLD' in b])}")

        if len(ohlcv) < 50:
            log("Not enough data → flat")
            return TargetAllocation(alloc)

        # -----------------------------------------------------
        # Price series
        # -----------------------------------------------------
        px = {t: self.closes(ohlcv, t) for t in self.tickers}

        # -----------------------------------------------------
        # Macro regime (NO SMA ON DERIVED SERIES)
        # -----------------------------------------------------
        spy_m = self.monthly(px["SPY"])
        gld_m = self.monthly(px["GLD"])

        if len(spy_m) < 6:
            log("Macro insufficient → SHY")
            alloc["SHY"] = 1.0
            return TargetAllocation(alloc)

        ratio = []
        for i in range(min(len(spy_m), len(gld_m))):
            ratio.append(spy_m[i] / gld_m[i] if gld_m[i] != 0 else 0)

        # manual SMA (FIX)
        window = min(6, len(ratio))
        ratio_sma = sum(ratio[-window:]) / window

        risk_on = ratio[-1] > ratio_sma

        log(f"RiskOn={risk_on} ratio={ratio[-1]:.3f} sma={ratio_sma:.3f}")

        # -----------------------------------------------------
        # CPI (correct API)
        # -----------------------------------------------------
        cpi = data.get(("median_cpi",))
        inflation = cpi[-1]["value"] if cpi else 2.5

        inflation_high = inflation > 3.5
        log(f"CPI={inflation:.2f} high={inflation_high}")

        # -----------------------------------------------------
        # Momentum
        # -----------------------------------------------------
        mom = {t: self.mom6(px[t]) for t in self.tickers}

        # -----------------------------------------------------
        # Trend filter (CORRECT EMA/SMA USAGE)
        # -----------------------------------------------------
        def trend(t):
            if len(px[t]) < 120:
                return False
            ema = EMA(t, ohlcv, 100)
            if ema is None:
                return False
            return px[t][-1] > ema[-1]

        # -----------------------------------------------------
        # Decision
        # -----------------------------------------------------
        selected = None

        if risk_on:

            if mom["CWB"] and mom["HYG"] and mom["CWB"] > mom["HYG"] and trend("CWB"):
                selected = "CWB"
            else:
                selected = "HYG"

            log(f"RiskOn → {selected}")

        else:

            if inflation_high:

                selected = "TIP" if (mom["TIP"] and mom["TIP"] > mom["SHY"]) else "SHY"

            else:

                selected = "TLT" if (mom["TLT"] and mom["IEF"] and trend("TLT") and mom["TLT"] > mom["IEF"]) else "IEF"

            log(f"Defensive → {selected}")

        # -----------------------------------------------------
        # Vol targeting
        # -----------------------------------------------------
        vol = self.vol20(px[selected])

        if not vol:
            exposure = 1.0
        else:
            exposure = min(1.0, max(0.0, 0.10 / vol))

        alloc[selected] = exposure

        log(f"FINAL {selected} vol={vol} exp={exposure:.3f}")

        return TargetAllocation(alloc)