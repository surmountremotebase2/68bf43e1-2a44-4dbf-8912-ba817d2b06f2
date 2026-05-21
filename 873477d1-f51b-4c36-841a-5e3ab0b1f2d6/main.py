from surmount.base_class import Strategy, TargetAllocation
from surmount.technical_indicators import SMA
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
        return [bar[ticker]["close"] for bar in ohlcv if ticker in bar]

    def monthly(self, series):
        return series[::21] if len(series) > 21 else series

    def mom6(self, series):
        lookback = 126
        if len(series) < lookback + 1:
            return None
        return (series[-1] / series[-lookback]) - 1

    def vol20(self, series):
        if len(series) < 22:
            return None

        rets = []
        for i in range(-20, 0):
            if series[i - 1] == 0:
                continue
            rets.append(series[i] / series[i - 1] - 1)

        if len(rets) < 5:
            return None

        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)

        return math.sqrt(var) * math.sqrt(252)

    # =========================================================
    # Main
    # =========================================================

    def run(self, data):

        ohlcv = data["ohlcv"]
        allocations = {t: 0.0 for t in self.tickers}

        if len(ohlcv) < 50:
            log("Not enough OHLCV data → flat allocation")
            return TargetAllocation(allocations)

        # ---------------------------------------------------------
        # Price series
        # ---------------------------------------------------------
        px = {}
        for t in self.tickers:
            px[t] = self.closes(ohlcv, t)

        log(f"Data availability SPY={len(px['SPY'])} GLD={len(px['GLD'])}")

        # ---------------------------------------------------------
        # Macro regime SPY/GLD
        # ---------------------------------------------------------
        spy_m = self.monthly(px["SPY"])
        gld_m = self.monthly(px["GLD"])

        if len(spy_m) < 5 or len(gld_m) < 5:
            log("Insufficient macro monthly data → default SHY")
            allocations["SHY"] = 1.0
            return TargetAllocation(allocations)

        ratio = [
            spy_m[i] / gld_m[i] if gld_m[i] != 0 else 0
            for i in range(min(len(spy_m), len(gld_m)))
        ]

        ratio_sma = SMA(ratio, 6)

        if ratio_sma is None:
            log("Ratio SMA unavailable → SHY fallback")
            allocations["SHY"] = 1.0
            return TargetAllocation(allocations)

        risk_on = ratio[-1] > ratio_sma[-1]

        log(f"RiskOn={risk_on} ratio={ratio[-1]:.3f} sma={ratio_sma[-1]:.3f}")

        # ---------------------------------------------------------
        # CPI via MedianCPI (CORRECT METHOD)
        # ---------------------------------------------------------
        cpi_data = data.get(("median_cpi",))
        if not cpi_data:
            inflation = 2.5
            log("Missing CPI → default 2.5")
        else:
            inflation = cpi_data[-1]["value"]

        inflation_regime = inflation > 3.5
        log(f"Inflation={inflation:.2f} High={inflation_regime}")

        # ---------------------------------------------------------
        # Momentum
        # ---------------------------------------------------------
        mom = {t: self.mom6(px[t]) for t in self.tickers}

        # ---------------------------------------------------------
        # Trend filters via SMA (SURMOUNT)
        # ---------------------------------------------------------
        def trend(t):
            if len(px[t]) < 30:
                return False
            sma = SMA(px[t], 10)
            if sma is None:
                return False
            return px[t][-1] > sma[-1]

        # ---------------------------------------------------------
        # Decision engine
        # ---------------------------------------------------------
        selected = None

        if risk_on:

            cwb_ok = trend("CWB")
            if mom["CWB"] and mom["HYG"] and mom["CWB"] > mom["HYG"] and cwb_ok:
                selected = "CWB"
            else:
                selected = "HYG"

            log(f"Risk-On → {selected}")

        else:

            if inflation_regime:

                if mom["TIP"] and mom["SHY"] and mom["TIP"] > mom["SHY"]:
                    selected = "TIP"
                else:
                    selected = "SHY"

                log(f"Inflation defense → {selected}")

            else:

                tlt_ok = trend("TLT")

                if mom["TLT"] and mom["IEF"] and tlt_ok and mom["TLT"] > mom["IEF"]:
                    selected = "TLT"
                else:
                    selected = "IEF"

                log(f"Duration regime → {selected}")

        # ---------------------------------------------------------
        # Vol targeting
        # ---------------------------------------------------------
        vol = self.vol20(px[selected])

        if not vol or vol == 0:
            exposure = 1.0
        else:
            exposure = min(1.0, max(0.0, 0.10 / vol))

        allocations[selected] = exposure

        log(
            f"FINAL → {selected} | "
            f"vol={vol:.4f if vol else None} | "
            f"exp={exposure:.3f}"
        )

        return TargetAllocation(allocations)