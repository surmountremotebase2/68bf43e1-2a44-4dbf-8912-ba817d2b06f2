from surmount.base_class import Strategy, TargetAllocation
from surmount.data import MedianCPI
from surmount.logging import log
from datetime import datetime
import math


class TradingStrategy(Strategy):
    """
    FixedIncome500 v4 — literature-based core-satellite FI.

    Evidence base:
    - Cross-sectional bond-ETF momentum rotation: falsified
      (TuringTrader; our v2/v3). Not used.
    - Carry is the dominant FI return source (Brooks et al. 2018;
      Beekhuizen et al. 2019) -> always-invested belly-of-curve core.
    - Credit momentum vs duration-matched treasuries, 6m, strongest
      in HY (Jostova et al. 2013) -> HYG-IEF relative signal.
    - 12m time-series momentum on bonds (Moskowitz et al. 2012)
      -> per-sleeve absolute trend gate vs cash, not rotation.
    - Inflation direction (not level) for duration risk -> CPI
      acceleration test on MedianCPI.

    Stateless: every bar recomputes the most recent Thursday-
    anchored decision from a slice of history. No instance state
    required for correctness.
    """

    CORE = {"SHY": 0.15, "UUP": 0.15}   # 40% always on
    W_DURATION = 0.30
    W_CREDIT = 0.30

    def __init__(self):
        self.tickers = [
            "TLT", "IEF", "LQD", "TIP",
            "HYG", "SHY", "BIL", "UUP",
            "SPY",  # benchmark only — never allocated
        ]
        self.data_list = [MedianCPI()]
        self.min_bars = 140   # signals degrade gracefully below 252
        self._cache = {}      # speedup only

    @property
    def assets(self):
        return self.tickers

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return self.data_list

    # ---------------- date / slicing ----------------
    def bar_date(self, ohlcv, i):
        bar = ohlcv[i]
        for t in self.tickers:
            try:
                v = bar.get(t)
                if v and v.get("date"):
                    return str(v["date"])[:10]
            except Exception:
                pass
        return None

    def iso_tuple(self, ds):
        d = datetime.strptime(ds, "%Y-%m-%d")
        return d.isocalendar()  # (year, week, weekday)

    def find_decision_index(self, ohlcv):
        """Most recent first-bar-of-week with weekday >= Thursday."""
        n = len(ohlcv)
        lo = max(1, n - 15)
        for i in range(n - 1, lo - 1, -1):
            ds, dsp = self.bar_date(ohlcv, i), self.bar_date(ohlcv, i - 1)
            if ds is None or dsp is None:
                continue
            try:
                y, w, wd = self.iso_tuple(ds)
                py, pw, pwd = self.iso_tuple(dsp)
            except Exception:
                continue
            if wd >= 4 and ((py, pw) != (y, w) or pwd < 4):
                return i, ds
        return None, None

    # ---------------- signal helpers ----------------
    def get_closes(self, ohlcv_slice, ticker):
        out = []
        for bar in ohlcv_slice:
            try:
                v = bar.get(ticker)
                if v and v.get("close") and v["close"] > 0:
                    out.append(float(v["close"]))
            except Exception:
                pass
        return out

    def momentum(self, prices, lb):
        if len(prices) <= lb:
            return None
        prev = prices[-1 - lb]
        if prev is None or prev <= 0:
            return None
        return prices[-1] / prev - 1.0

    def excess(self, prices, cash, lb):
        a, c = self.momentum(prices, lb), self.momentum(cash, lb)
        if a is None or c is None:
            return None
        return a - c

    def tsmom_on(self, prices, cash):
        """12m excess trend vs cash; falls back to 6m if history short."""
        ex = self.excess(prices, cash, 252)
        if ex is None:
            ex = self.excess(prices, cash, 126)
        return ex is not None and ex > 0

    def cpi_accelerating(self, cpi_series):
        """Median CPI now vs ~6 monthly readings ago, rising > 0.3pt."""
        try:
            if not cpi_series or len(cpi_series) < 7:
                return False
            now = cpi_series[-1].get("value")
            then = cpi_series[-7].get("value")
            if now is None or then is None:
                return False
            return (now - then) > 0.3
        except Exception:
            return False

    def park_in_cash(self):
        parked = {t: 0.0 for t in self.tickers}
        parked["BIL"] = 1.0
        return TargetAllocation(parked)

    # ---------------- pure decision function ----------------
    def compute_allocation(self, ohlcv_slice, cpi_series, date_str):
        closes = {t: self.get_closes(ohlcv_slice, t) for t in self.tickers}
        short = [t for t in self.tickers if len(closes[t]) < self.min_bars]
        if short:
            log(f"{date_str}: park (insufficient bars: {short})")
            return None

        cash = closes["BIL"]
        weights = dict(self.CORE)  # carry core, always on

        # --- Duration sleeve (30%) ---
        infl_up = self.cpi_accelerating(cpi_series)
        dur_note = "defensive"
        if not infl_up and self.tsmom_on(closes["TLT"], cash):
            weights["TLT"] = weights.get("TLT", 0) + self.W_DURATION
            dur_note = "TLT"
        elif infl_up and self.tsmom_on(closes["TIP"], cash):
            weights["TIP"] = weights.get("TIP", 0) + self.W_DURATION
            dur_note = "TIP"
        else:
            weights["SHY"] = weights.get("SHY", 0) + self.W_DURATION * 0.5
            weights["BIL"] = weights.get("BIL", 0) + self.W_DURATION * 0.5

        # --- Credit sleeve (30%) ---
        # Credit momentum = 6m return minus duration-matched
        # treasury proxy (IEF); require 12m excess vs cash too.
        cred_note = "defensive"
        hy_credit = self.excess(closes["HYG"], closes["IEF"], 126)
        ig_credit = self.excess(closes["LQD"], closes["IEF"], 126)
        if (
            hy_credit is not None and hy_credit > 0
            and self.tsmom_on(closes["HYG"], cash)
        ):
            weights["HYG"] = weights.get("HYG", 0) + self.W_CREDIT
            cred_note = "HYG"
        elif (
            ig_credit is not None and ig_credit > 0
            and self.tsmom_on(closes["LQD"], cash)
        ):
            weights["LQD"] = weights.get("LQD", 0) + self.W_CREDIT
            cred_note = "LQD"
        else:
            weights["SHY"] = weights.get("SHY", 0) + self.W_CREDIT * 0.5
            weights["BIL"] = weights.get("BIL", 0) + self.W_CREDIT * 0.5

        allocation = {t: 0.0 for t in self.tickers}
        for t, w in weights.items():
            if t in allocation:
                allocation[t] = round(w, 4)
        total = sum(allocation.values())
        if total > 1.0:
            allocation = {k: v / total for k, v in allocation.items()}

        held = [(t, round(w, 3)) for t, w in allocation.items() if w > 0]
        log(
            f"Decision {date_str} | infl_up={infl_up} "
            f"| dur={dur_note} | credit={cred_note} | {held}"
        )
        return allocation

    # ---------------- main ----------------
    def run(self, data):
        try:
            ohlcv = data["ohlcv"]
            if len(ohlcv) < self.min_bars:
                return self.park_in_cash()

            idx, decision_date = self.find_decision_index(ohlcv)
            if idx is None:
                return self.park_in_cash()
            if decision_date in self._cache:
                return TargetAllocation(self._cache[decision_date])

            cpi_series = data.get(("median_cpi",))
            allocation = self.compute_allocation(
                ohlcv[: idx + 1], cpi_series, decision_date
            )
            if allocation is None:
                return self.park_in_cash()

            self._cache[decision_date] = allocation
            return TargetAllocation(allocation)

        except Exception as e:
            log(f"Error: {e}")
            return self.park_in_cash()