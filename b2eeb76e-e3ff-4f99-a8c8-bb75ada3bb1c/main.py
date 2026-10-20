from surmount.base_class import Strategy, TargetAllocation
from surmount.logging import log
import numpy as np
import pandas as pd
import math


class TradingStrategy(Strategy):
    """
    Moderate: ROAR-score-driven ETF allocation inside a fixed equity band. Long only, no leverage, daily bars.

    Risk profile: anchor 60% equity, band 50% to 65%. The rest is bonds and short-term (BIL >= 2%).

    Universe (14 scored ETFs + cash):
      Equity: VTI VIG XLV XLP XLU EFA VWO VNQ     Bonds: AGG SHY IEF TLT TIP LQD     Cash: BIL
      SPY is listed in `assets` for benchmarking only and always receives a 0% target.

    Score per ETF (ROAR style), from data up to the current bar only:
      For MA periods 20 / 50 / 150:
        MA rating   (curvature of the MA: Buy 5 / Hold 2 / Sell 0)
        Dir score   (slope percentile + acceleration category, mapped by rating)
        Str score   (period % change bucket, mapped by rating)
      Vol score     (inverse decile of 15-day realised vol vs its prior 126 observations, -10..+10)
      Raw ROAR      = 25 * weighted sum (original ROAR weights) - 100 * blended % change (5/10/20/50d)
      ROAR          = 10-day mean of Raw ROAR
      Score         = clip((ROAR - 50) / 5, -10, +10), so ROAR 50 = neutral, 100 = +10, 0 = -10.
    Everything price-unit based (slope, accel, strength buckets, blend) is scaled by each ETF's own daily vol
    relative to a 1% reference (SPY-like), so thresholds tuned on SPY do not bias bonds or low-vol sectors.

    Allocation, guardrails, vol target, rebalance logic: unchanged from the previous version.
    """

    def __init__(self):
        # Universe
        self.equity = ["VTI", "VIG", "XLV", "QQQ", "RSP", "EFA", "VWO", "VNQ"]
        self.bonds = ["AGG", "SHY", "IEF", "BND", "TIP", "LQD"]
        self.cash = "BIL"
        self.benchmark = "SPY"
        self.trading = self.equity + self.bonds + [self.cash]

        # Risk profile band
        self.e_anchor = 0.6
        self.e_floor = 0.5
        self.e_ceil = 0.65
        self.cash_min = 0.02
        self.max_weight = 0.25

        # ROAR scoring
        self.vol_window = 15
        self.vol_lookback = 126
        self.sig_window = 126          # daily-vol estimate used for scaling
        self.ref_vol = 0.01            # SPY-like daily vol reference
        self.slope_win = 252           # window for slope percentile thresholds
        self.s_thr = 0.022             # 0.1 price units on SPY ~450, in vol-normalised units
        self.a_thr = 0.011             # 0.05
        self.r_thr = 0.0044            # 0.02
        self.smooth = 10
        self.roar_neutral = 30.0
        self.roar_scale = 5.0
        # (period, w_ma, w_dir, w_str, strength thresholds)
        self.ma_cfg = [
            (20, 0.12, 0.12, 0.08, [-0.02, 0.03, 0.05, 0.08]),
            (50, 0.12, 0.12, 0.08, [-0.05, 0.04, 0.08, 0.12]),
            (150, 0.08, 0.05, 0.05, [-0.05, 0.05, 0.10, 0.15]),
        ]
        self.w_vol = 0.10

        # Volatility targeting
        self.use_vol_target = True
        self.vt_lookback = 126
        self.vt_target = 0.10

        # Selection
        self.n_eq = 5
        self.n_bd = 4
        self.max_sleeve_weight = 0.40

        # Rebalance schedule: every 3 months (calendar quarters)
        self.rebalance_months = 1

        # History: MA150 + slope percentile (min 30) + 10-day smoothing = 190 bars, 200 with margin.
        # Kept below the 221 the previous version needed: the platform may cap the lookback it hands to run().
        self.bars = 200

    @property
    def assets(self):
        return self.trading + [self.benchmark]

    @property
    def interval(self):
        return "1day"

    @property
    def data(self):
        return []  # price data only

    # ---------- helpers ----------
    @staticmethod
    def _stamp(bar):
        for v in bar.values():
            return str(v["date"])
        return ""

    def _period(self, bar):
        stamp = self._stamp(bar)
        try:
            return (int(stamp[:4]) * 12 + int(stamp[5:7]) - 1) // self.rebalance_months
        except ValueError:
            return -1

    def _frame(self, rows):
        return pd.DataFrame({t: [bar[t]["close"] if t in bar else float("nan") for bar in rows]
                             for t in self.trading})

    @staticmethod
    def _top(score, universe, n):
        return sorted(universe, key=lambda c: (-score[c], universe.index(c)))[:n]

    @staticmethod
    def _cap_normalize(tilt, cap):
        tot = sum(tilt.values())
        w = {k: v / tot for k, v in tilt.items()}
        for _ in range(10):
            over = [k for k in w if w[k] > cap + 1e-12]
            if not over:
                break
            excess = sum(w[k] - cap for k in over)
            for k in over:
                w[k] = cap
            under = [k for k in w if k not in over and 0 < w[k] < cap - 1e-12]
            if not under:
                break
            s = sum(w[k] for k in under)
            for k in under:
                w[k] += excess * w[k] / s
        return w

    def _roar(self, close):
        """ROAR score of the last bar mapped to -10..+10. NaN if not computable."""
        idx = close.index
        rets = close.pct_change()
        sig = rets.rolling(self.sig_window, min_periods=60).std()
        k = sig / self.ref_vol
        total = pd.Series(0.0, index=idx)
        a = self.a_thr

        for period, w_ma, w_dir, w_str, th in self.ma_cfg:
            ma = close.rolling(period).mean()
            slope = ma.diff() / (ma * sig)
            accel = slope.diff()
            rec = accel.rolling(3).mean()

            # Rating by curvature: 1 Buy, 0 Hold, -1 Sell (NaN comparisons fall to Hold)
            buy = (slope > self.s_thr) & (accel > a) & (rec > 0)
            sell = (slope < -self.s_thr) | ((accel < -a) & (rec < -self.r_thr))
            rating = np.select([buy, sell], [1, -1], 0)
            ma_score = np.select([rating == 1, rating == 0], [5, 2], 0)

            # Direction: 0 Strongest, 1 Strengthening, 2 Average, 3 Weakening, 4 Weakest
            thr_s = slope.rolling(self.slope_win, min_periods=30).quantile(0.65)
            thr_w = slope.rolling(self.slope_win, min_periods=30).quantile(0.35)
            cat = np.select([slope > thr_s,
                             (slope < thr_w) & (accel < -a),
                             (slope < thr_w) & (accel > a),
                             (slope > thr_w) & (accel < -a)], [0, 4, 1, 3], 2)
            dir_buy, dir_hold, dir_sell = np.array([5, 4, 2, 1, 0]), np.array([3, 2, 2, 1, 0]), np.array([0, 0, 0, 1, 2])
            dir_score = np.where(rating == 1, dir_buy[cat], np.where(rating == 0, dir_hold[cat], dir_sell[cat]))

            # Strength: 0 Weak, 1 Soft, 2 Average, 3 Strong, 4 Maximum (thresholds scaled by vol)
            pct = close.pct_change(periods=period)
            t = [x * k for x in th]
            code = np.select([pct.isna(), pct <= t[0], pct <= t[1], pct <= t[2], pct <= t[3]], [2, 0, 1, 2, 3], 4)
            str_ns, str_s = np.array([0, 1, 2, 4, 5]), np.array([2, 1, 1, 0, 0])
            str_score = np.where(rating == -1, str_s[code], str_ns[code])

            total += w_ma * pd.Series(ma_score, index=idx)
            total += w_dir * pd.Series(dir_score, index=idx)
            total += w_str * pd.Series(str_score, index=idx)

        # Inverse realised-vol decile score vs the prior distribution (current bar excluded)
        rv = rets.rolling(self.vol_window).std() * math.sqrt(252)
        prev = rv.shift(1)
        decs = [prev.rolling(self.vol_lookback, min_periods=20).quantile(i / 10.0) for i in range(1, 10)]
        rank = sum((rv > d).astype(int) for d in decs)
        vscore = (10.0 - rank * (20.0 / 9.0)).where(rv.notna() & decs[0].notna())
        total += self.w_vol * vscore

        blend = (close.pct_change(5) + close.pct_change(10) + close.pct_change(20) + close.pct_change(50)) / 4.0
        raw = total * 25.0 - (blend / k) * 100.0
        roar = raw.rolling(self.smooth).mean().iloc[-1]
        if pd.isna(roar):
            return float("nan")
        return max(-10.0, min(10.0, (float(roar) - self.roar_neutral) / self.roar_scale))

    def _target(self, df):
        """Target weights from data up to the current bar. Returns (weights dict or None, info dict)."""
        rets = df.pct_change()
        scored = self.equity + self.bonds
        score = {t: self._roar(df[t]) for t in scored}
        if any(pd.isna(v) for v in score.values()):
            return None, {}

        # Equity sleeve: relative ranking
        eq = self._top(score, self.equity, self.n_eq)
        tilt_e = {c: max(score[c] + 10.0, 1.0) for c in eq}
        w_eq = self._cap_normalize(tilt_e, self.max_sleeve_weight)

        # Volatility target on the selected equity basket
        sig_eq, scale = float("nan"), 1.0
        if self.use_vol_target:
            r = sum(rets[c].iloc[-self.vt_lookback:] * w_eq[c] for c in eq)
            sig_eq = float(r.std() * math.sqrt(252))
            if sig_eq > 0:
                scale = min(1.0, self.vt_target / sig_eq)
        e_t = min(max(self.e_anchor * scale, self.e_floor), self.e_anchor)
        w_eq = self._cap_normalize(tilt_e, min(self.max_sleeve_weight, self.max_weight / e_t))

        # Bond sleeve: absolute gate (score > 0, i.e. ROAR > neutral), unallocated share goes to cash
        bd = self._top(score, self.bonds, self.n_bd)
        tilt_b = {c: max(score[c], 0.0) for c in bd}
        bond_budget = 1.0 - self.cash_min - e_t
        cap_b = min(self.max_sleeve_weight, self.max_weight / bond_budget)
        w_bd = self._cap_normalize(tilt_b, cap_b) if sum(tilt_b.values()) > 0 else {c: 0.0 for c in bd}

        tgt = {a: 0.0 for a in self.trading}
        for c in eq:
            tgt[c] = e_t * w_eq[c]
        for c in bd:
            tgt[c] = bond_budget * w_bd[c]
        tgt[self.cash] = max(0.0, 1.0 - sum(v for k, v in tgt.items() if k != self.cash) - 1e-9)
        return tgt, dict(equity_target=e_t, vol_scale=scale, equity_vol=sig_eq)

    def _valid(self, w):
        e = sum(w[c] for c in self.equity)
        return (sum(w.values()) <= 1.0 + 1e-9 and min(w.values()) >= -1e-12
                and max(v for k, v in w.items() if k != self.cash) <= self.max_weight + 1e-9
                and self.e_floor - 1e-9 <= e <= self.e_ceil + 1e-9)

    def _alloc(self, w):
        out = {a: float(w.get(a, 0.0)) for a in self.trading}
        out[self.benchmark] = 0.0
        total = sum(out.values())
        if total > 1.0:
            out = {k: v / total for k, v in out.items()}
        return TargetAllocation(out)

    # ---------- strategy ----------
    def run(self, data):
        ohlcv = data["ohlcv"]
        if len(ohlcv) < self.bars:
            if len(ohlcv) % 50 == 0:
                log("WAITING_FOR_HISTORY|have=%d|need=%d" % (len(ohlcv), self.bars))
            return TargetAllocation({})  # not enough history: stay in cash

        holdings = data.get("holdings") or {}
        cur = {a: float(holdings.get(a) or 0.0) for a in self.trading}
        invested = sum(cur.values())
        equity_now = sum(cur[a] for a in self.equity)

        new_period = self._period(ohlcv[-1]) != self._period(ohlcv[-2])
        if invested < 0.5:
            reason = "initial"
        elif new_period:
            reason = "scheduled"
        elif equity_now < self.e_floor - 1e-9 or equity_now > self.e_ceil + 1e-9:
            reason = "band"
        else:
            return self._alloc(cur)

        rows = ohlcv[-self.bars:]
        df = self._frame(rows)
        held = invested >= 0.5
        fallback = self._alloc(cur) if held else TargetAllocation({})
        if df[self.equity + self.bonds].isna().any().any() or pd.isna(df[self.cash].iloc[-1]):
            log("%s|SKIP_MISSING_DATA|held=%s|%s" % (self._stamp(ohlcv[-1])[:10], held, reason))
            return fallback

        tgt, info = self._target(df)
        if tgt is None:
            log("%s|SKIP_INSUFFICIENT_SCORES|held=%s|%s" % (self._stamp(ohlcv[-1])[:10], held, reason))
            return fallback
        if not self._valid(tgt):
            log("%s|GUARDRAIL_BREACH_KEPT_PREVIOUS|%s" % (self._stamp(ohlcv[-1])[:10], reason))
            return fallback

        #log("%s|%s|eq=%.3f|scale=%.2f|eqvol=%.3f|%s" % (
        #    self._stamp(ohlcv[-1])[:10], reason, info["equity_target"], info["vol_scale"], info["equity_vol"],
        #    ",".join("%s:%.4f" % (k, v) for k, v in tgt.items() if v > 1e-9)))
        return self._alloc(tgt)