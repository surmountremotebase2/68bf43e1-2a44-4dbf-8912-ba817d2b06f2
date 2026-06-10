# =============================================================================
# Opening Range Breakout (ORB) — Surmount implementation
#
# Replicates the strategy logic from Concretum Group's article
# "How to Backtest an ORB Strategy in Python Using Alpaca", itself based on
# Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?".
#
# Original rules:
#   - First 5 minutes of the session define direction (bullish/bearish candle)
#   - Enter at the open of the next bar
#   - Stop: opening-range high/low ("HL" mode) OR 5% of the 14-day ATR ("ATR")
#   - HL mode uses a 10R profit target; ATR mode holds to the close
#   - Risk 1% of equity per trade; exit at stop, target, or end of day
#
# Framework adaptations (documented, deliberate — do not remove silently):
#   1. Surmount allocations are long-only in [0, 1]. The short leg is proxied
#      with SQQQ (3x inverse of QQQ), mirroring TQQQ on the long leg.
#   2. The article's 4x leverage cap is unreachable here; sizing is capped
#      at 100% of equity. Expect lower CAGR and lower drawdown vs. the paper.
#   3. Interval is 5-minute bars: the opening range is exactly the first bar,
#      and "open of the 6th 1-min bar" maps to the open of the 2nd 5-min bar.
#   4. The engine is stateless per call, so the day's trade (entry, stop,
#      whether the stop/target was already hit) is *re-derived* from today's
#      bars on every run() call. Deterministic — no hidden state required.
# =============================================================================

from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
from datetime import datetime


class TradingStrategy(Strategy):

    def __init__(self):
        # Signal and risk are computed on TQQQ prices (the article's ticker).
        # SQQQ is only the *instrument* used to express a bearish opening range.
        self.signal_ticker = "TQQQ"
        self.inverse_ticker = "SQQQ"

        # --- ORB parameters (mirroring the article's defaults) -------------
        self.stop_mode = "ATR"      # "ATR" (hold to close) or "HL" (10R target)
        self.atr_period = 14        # 14-day ATR, computed on daily aggregates
        self.atr_stop_mult = 0.05   # stop width = 5% of 14-day ATR
        self.profit_target_r = 10   # only active in HL mode
        self.risk_per_trade = 0.01  # risk 1% of equity per trade
        self.max_alloc = 1.0        # framework cap (article allowed 4x)
        self.eod_exit_hhmm = "15:55"  # flatten before the close (ET session)

    @property
    def assets(self):
        return [self.signal_ticker, self.inverse_ticker]

    @property
    def interval(self):
        return "5min"

    @property
    def data(self):
        return []  # OHLCV only; no alternative datasets required

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _parse_dt(self, bar):
        """Return (date_str, time_str) from a bar's 'date' field, tolerating
        daily-format timestamps that lack a time component."""
        raw = bar[self.signal_ticker]["date"]
        if " " in raw:
            d, t = raw.split(" ", 1)
            return d, t[:5]            # "HH:MM"
        return raw, "00:00"

    def _daily_atr_pct(self, ohlcv, today_str):
        """14-day ATR as a fraction of price, built by aggregating intraday
        bars into daily OHLC for all sessions *before* today (lagged ATR,
        as in the article: yesterday's ATR drives today's stop)."""
        days = {}  # date -> [open, high, low, close] preserving order
        order = []
        for bar in ohlcv:
            b = bar[self.signal_ticker]
            d, _ = self._parse_dt(bar)
            if d >= today_str:
                continue               # strictly prior sessions only
            if d not in days:
                days[d] = [b["open"], b["high"], b["low"], b["close"]]
                order.append(d)
            else:
                rec = days[d]
                rec[1] = max(rec[1], b["high"])
                rec[2] = min(rec[2], b["low"])
                rec[3] = b["close"]

        if len(order) < self.atr_period + 1:
            return None                # insufficient history → no trade

        trs = []
        for i in range(1, len(order)):
            _, h, l, _ = days[order[i]]
            prev_close = days[order[i - 1]][3]
            trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        atr = sum(trs[-self.atr_period:]) / self.atr_period
        ref_price = days[order[-1]][3]  # normalize by yesterday's close
        return atr / ref_price if ref_price > 0 else None

    # ------------------------------------------------------------------ #
    # Core logic                                                          #
    # ------------------------------------------------------------------ #

    def run(self, data):
        flat = TargetAllocation({self.signal_ticker: 0, self.inverse_ticker: 0})
        ohlcv = data.get("ohlcv") if isinstance(data, dict) else None
        if not ohlcv or len(ohlcv) < 2:
            return flat                                # no usable data

        # Defensive: the signal ticker must be present in the latest bar
        if self.signal_ticker not in ohlcv[-1]:
            return flat

        today_str, now_hhmm = self._parse_dt(ohlcv[-1])

        # --- End-of-day exit: flatten everything near the close -----------
        if now_hhmm >= self.eod_exit_hhmm:
            return flat

        # --- Collect today's bars -----------------------------------------
        today_bars = [b for b in ohlcv if self._parse_dt(b)[0] == today_str]
        if len(today_bars) < 2:
            return flat   # still inside the opening range — no entry yet

        # --- Opening range = first 5-minute bar of the session ------------
        orb = today_bars[0][self.signal_ticker]
        if orb["close"] > orb["open"]:
            direction = 1     # bullish opening candle → long TQQQ
        elif orb["close"] < orb["open"]:
            direction = -1    # bearish opening candle → long SQQQ (short proxy)
        else:
            return flat       # doji: the paper takes no trade

        # --- Entry at the open of the bar following the opening range ------
        entry = today_bars[1][self.signal_ticker]["open"]
        if entry <= 0:
            return flat

        # --- Stop placement -------------------------------------------------
        # Both stops are expressed on the TQQQ price path; the SQQQ leg is
        # exited when TQQQ crosses its (upside) stop, since SQQQ ≈ -1x TQQQ
        # in daily percentage terms.
        if self.stop_mode == "ATR":
            atr_pct = self._daily_atr_pct(ohlcv, today_str)
            if atr_pct is None:
                return flat
            stop_width = self.atr_stop_mult * atr_pct * entry
        else:  # "HL": opening-range low (long) / high (short)
            stop_width = (entry - orb["low"]) if direction == 1 \
                         else (orb["high"] - entry)

        if stop_width <= 0:
            return flat        # degenerate range (e.g. gap through the range)

        stop_price = entry - direction * stop_width
        target_price = (entry + direction * self.profit_target_r * stop_width
                        if self.stop_mode == "HL" else None)

        # --- Replay today's bars since entry: was the trade already closed? -
        # One trade per day, no re-entry — exactly as in the article's engine.
        for bar in today_bars[1:]:
            b = bar[self.signal_ticker]
            if direction == 1:
                if b["low"] <= stop_price:
                    return flat                     # long stopped out
                if target_price and b["high"] >= target_price:
                    return flat                     # 10R target hit (HL mode)
            else:
                if b["high"] >= stop_price:
                    return flat                     # short proxy stopped out
                if target_price and b["low"] <= target_price:
                    return flat

        # --- Position sizing: risk 1% of equity against the stop -----------
        # fraction = risk / (stop distance in % of entry), capped at 100%.
        # The article allows up to 4x here; the framework cannot, so trades
        # with wide ATR stops are sized smaller than the published backtest.
        alloc = min(self.max_alloc,
                    self.risk_per_trade / (stop_width / entry))

        log(f"ORB {today_str} dir={'LONG' if direction == 1 else 'SHORT'} "
            f"entry={entry:.2f} stop={stop_price:.2f} alloc={alloc:.3f}")

        if direction == 1:
            return TargetAllocation({self.signal_ticker: alloc,
                                     self.inverse_ticker: 0})
        return TargetAllocation({self.signal_ticker: 0,
                                 self.inverse_ticker: alloc})