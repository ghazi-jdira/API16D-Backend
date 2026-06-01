"""
NIST nitrogen-property lookup engine (server-side).

Direct port of the browser engine (js/nist.js): bilinear interpolation in
(Temperature, Pressure) for density / entropy, inverse density->pressure
lookup, and an entropy-match temperature lookup used by Method C.

Data: data/nist.json -> {temps, pgrids, pidx, D, S}.
This module is intentionally identical in behaviour to nist.js so results
match the validated workbook reference case.
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


class Nist:
    def __init__(self, raw):
        self.temps = raw["temps"]
        self.pgrids = raw["pgrids"]
        self.pidx = raw["pidx"]
        self.D = raw["D"]
        self.S = raw["S"]
        self.N = len(self.temps)

    @staticmethod
    def _last_le(arr, x):
        """Largest index i such that arr[i] <= x (arr ascending)."""
        lo, hi, r = 0, len(arr) - 1, 0
        while lo <= hi:
            m = (lo + hi) >> 1
            if arr[m] <= x:
                r = m
                lo = m + 1
            else:
                hi = m - 1
        return r

    def _pgrid_for(self, i):
        return self.pgrids[self.pidx[i]]

    def _interp_in_pressure(self, i, P, col):
        Pg = self._pgrid_for(i)
        a = col[i]
        j = self._last_le(Pg, P)
        if j >= len(Pg) - 1:
            j = len(Pg) - 2
        if j < 0:
            j = 0
        return a[j] + (a[j + 1] - a[j]) * (P - Pg[j]) / (Pg[j + 1] - Pg[j])

    def _interp_pressure_at_density(self, i, rho):
        Pg = self._pgrid_for(i)
        a = self.D[i]
        j = self._last_le(a, rho)
        if j >= len(a) - 1:
            j = len(a) - 2
        if j < 0:
            j = 0
        return Pg[j] + (Pg[j + 1] - Pg[j]) * (rho - a[j]) / (a[j + 1] - a[j])

    def _t_bracket(self, T):
        lo = self._last_le(self.temps, T)
        hi = min(lo + 1, self.N - 1)
        return lo, hi

    def _t_interp(self, T, fn_at_block):
        lo, hi = self._t_bracket(T)
        n_lo = fn_at_block(lo)
        n_hi = fn_at_block(hi)
        t_lo, t_hi = self.temps[lo], self.temps[hi]
        if T <= t_lo:
            return n_lo
        if T >= t_hi:
            return n_hi
        return n_lo + (T - t_lo) * (n_hi - n_lo) / (t_hi - t_lo)

    def density(self, T, P):
        return self._t_interp(T, lambda i: self._interp_in_pressure(i, P, self.D))

    def entropy(self, T, P):
        return self._t_interp(T, lambda i: self._interp_in_pressure(i, P, self.S))

    def pressure_from_density(self, T, rho):
        return self._t_interp(T, lambda i: self._interp_pressure_at_density(i, rho))

    def temp_at_entropy(self, target_s, p_mop):
        s_vals = [self._interp_in_pressure(i, p_mop, self.S) for i in range(self.N)]
        j = self._last_le(s_vals, target_s)
        if j >= self.N - 1:
            j = self.N - 2
        if j < 0:
            j = 0
        g = self.temps[j]
        ii = self.temps[j + 1]
        n_lo = s_vals[j]
        o_hi = s_vals[j + 1]
        if o_hi == n_lo:
            return g
        return g + (ii - g) * (target_s - n_lo) / (o_hi - n_lo)


def load_nist():
    with open(os.path.join(_DATA_DIR, "nist.json"), "r", encoding="utf-8") as f:
        return Nist(json.load(f))
