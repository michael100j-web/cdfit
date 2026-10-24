"""Other ways to show the same data, offered next to the default graph (the data as measured, as in Prism).

The skill asks the person which of these they want; none of them is applied unless chosen.

- per-molar units: mean residue ellipticity for CD ([θ], 10³ deg cm² dmol⁻¹) or molar absorption coefficient for
  absorbance (ε, 10³ M⁻¹ cm⁻¹), from the concentration, path length and number of residues the person gives;
- an off-peak reference: the absorbance at a second wavelength of the same scan subtracted (e.g. A225 − A285), which
  removes broadband drift and scattering from UV melts;
- fraction folded: each fitted melt rescaled with its own fitted baselines, F = (Y − U(T)) / (N(T) − U(T)), so curves
  with different signals, offsets or drifts (CD and UV, several runs or concentrations) share one 1 → 0 scale. The
  graph is an ordinary CD Fit graph: the CMP model on fixed baselines (REFN = 1, DEN = 0, REFU = 0, DEU = 0), so only
  Tm is fitted and it equals the original fit's Tm.
"""
from __future__ import annotations

import math
import re

import cdfit_engine as E

MRE_TITLE = "[*θ*] (10^{3} deg cm^{2} dmol^{−1})"
EPS_TITLE = "*ε* (10^{3} M^{−1} cm^{−1})"
FIXED_BASELINES = {"refn": {"value": "1", "fixed": True}, "den": {"value": "0", "fixed": True},
                   "refu": {"value": "0", "fixed": True}, "deu": {"value": "0", "fixed": True}}


class ReprError(ValueError):
    pass


# ---------------------------------------------------------------- tables
def _table(p):
    """parse_data output back to a tab-separated table."""
    head = "\t".join([p["xName"] or "X"] + list(p["names"]))
    rows = ["\t".join(E.js_str(v) if math.isfinite(v) else "" for v in r) for r in p["rows"]]
    return "\n".join([head] + rows)


def per_column(values, n, what):
    """'200' or '2,20' (one per Y column, separated by commas, semicolons or slashes) -> list of n floats."""
    vals = [float(v) for v in re.split(r"[,;/|]", str(values)) if v.strip()]
    if len(vals) == 1:
        return vals * n
    if len(vals) != n:
        raise ReprError(f"{what}: give one value or one per data column ({n}), got {len(vals)}")
    return vals


# ---------------------------------------------------------------- per-molar units
def molar_factors(conc_uM, path_cm, residues=None, absorbance=False):
    """Multipliers that turn mdeg into [θ] (10³ deg cm² dmol⁻¹) or absorbance into ε (10³ M⁻¹ cm⁻¹)."""
    if path_cm is None or not (path_cm > 0):
        raise ReprError("--path (cm) is needed with --conc")
    out = []
    for c in conc_uM:
        if not (c > 0):
            raise ReprError("concentrations must be positive (µM)")
        if absorbance:
            out.append(1000.0 / (c * path_cm))                     # A / (c[M] l) / 1000
        else:
            if not residues:
                raise ReprError("CD in mean residue ellipticity needs --residues (residues per strand)")
            out.append(100.0 / (path_cm * c * residues))           # θ[mdeg] / (10 l c[M] n) / 1000
    return out


def scale_columns(text, factors):
    p = E.parse_data(text)
    if len(factors) != len(p["names"]):
        raise ReprError(f"{len(factors)} factors for {len(p['names'])} data columns")
    for r in p["rows"]:
        for j, f in enumerate(factors):
            r[j + 1] = r[j + 1] * f if math.isfinite(r[j + 1]) else r[j + 1]
    return _table(p)


def molar_title(mode, absorbance, wavelength=None):
    sub = "" if mode == "spec" or wavelength is None else f"_{{{E.fmt_num(wavelength, 4)}}}"
    if absorbance:
        return EPS_TITLE.replace("*ε*", "*ε*" + sub)
    return MRE_TITLE.replace("[*θ*]", "[*θ*]" + sub)


# ---------------------------------------------------------------- off-peak reference
def subtract_reference(text, ref_text, ref_nm):
    """Each Y column minus the same column read at the reference wavelength (rows matched by X)."""
    p, q = E.parse_data(text), E.parse_data(ref_text)
    if len(p["names"]) != len(q["names"]):
        raise ReprError("the reference wavelength gave a different set of curves")
    ref = {round(r[0], 6): r for r in q["rows"]}
    rows = []
    for r in p["rows"]:
        s = ref.get(round(r[0], 6))
        if s is None:
            continue
        rows.append([r[0]] + [a - b if math.isfinite(a) and math.isfinite(b) else math.nan
                              for a, b in zip(r[1:], s[1:])])
    lab = E.fmt_num(ref_nm, 4)
    return _table({"xName": p["xName"], "names": [f"{n} − {lab} nm" for n in p["names"]], "rows": rows})


# ---------------------------------------------------------------- fraction folded
def has_baselines(model):
    return model is not None and all(k in model.keys for k in ("tm", "refn", "den", "refu", "deu"))


def fraction_of(session, ser):
    """(xs, F) for one fitted series, all its points (the faded ones outside the fit range too)."""
    fit = session.fit_of(ser)
    if not fit or fit.get("error") or not has_baselines(session.model):
        return None
    p = {k: fit["p"][i] for i, k in enumerate(session.model.keys)}
    out = []
    for x, y in sorted(zip(ser["xs"] + ser["xsEx"], ser["ys"] + ser["ysEx"])):
        k = x + 273.15
        n, u = p["refn"] + p["den"] * k, p["refu"] + p["deu"] * k
        if n != u and math.isfinite(y):
            out.append((x, (y - u) / (n - u)))
    return [a for a, _ in out], [b for _, b in out]


def fraction_series(session, columns=None, names=None):
    """[(name, xs, F)] of the visible fitted series of a session (columns: 0-based indices to keep)."""
    out = []
    for ser in session.data["series"]:
        if not session.S["series"][ser["idx"]].get("visible"):
            continue
        if columns is not None and ser["idx"] not in columns:
            continue
        r = fraction_of(session, ser)
        if r:
            out.append((ser["name"], r[0], r[1]))
    if names:
        out = [(names[i] if i < len(names) and names[i] else n, x, y) for i, (n, x, y) in enumerate(out)]
    return out


def fraction_state(series, eq_text=None, fmt=None, styles=None):
    """A CD Fit state for fraction folded: the series merged on X, CMP model on fixed 1/0 baselines."""
    keys = sorted({round(x, 6) for _, xs, _ in series for x in xs})
    pos = {k: i for i, k in enumerate(keys)}
    rows = [[k] + [math.nan] * len(series) for k in keys]
    for j, (_, xs, ys) in enumerate(series):
        for x, y in zip(xs, ys):
            rows[pos[round(x, 6)]][j + 1] = float(f"{y:.6g}")
    text = _table({"xName": "T (°C)", "names": [n for n, _, _ in series], "rows": rows})
    S = E.base_state("melt")
    S["dataText"] = text
    if eq_text:
        S["eqText"] = eq_text
    S["params"] = {k: dict(v) for k, v in FIXED_BASELINES.items()}
    S["stepDir"] = "any"
    S["fmt"].update({"yTitle": "Fraction folded", "yMin": "-0.2", "yMax": "1.2", "yStep": "0.2", "legend": "bl"})
    if fmt:
        S["fmt"].update(fmt)
    if styles:
        S["series"] = [dict(st or {}) for st in styles]
        for j, st in enumerate(S["series"]):
            st.setdefault("color", E.COLORS[j % len(E.COLORS)])
            st.setdefault("visible", True)
            st.setdefault("name", "")
    return S


def fraction_session(sessions_and_columns, names=None, fmt=None, styles=None):
    """One fraction-folded Session from several fitted sessions: [(session, columns or None)].
    The equation is the first session's (so a fixed ΔH other than −500 kJ/mol carries over)."""
    series = []
    eq = None
    for sess, cols in sessions_and_columns:
        if not has_baselines(sess.model):
            raise ReprError("fraction folded needs a fitted model with baselines REFN, DEN, REFU, DEU (the CMP or "
                            "two-state model)")
        eq = eq or sess.S.get("eqText")
        series += fraction_series(sess, cols)
    if not series:
        raise ReprError("no fitted curve to show as fraction folded")
    if names:
        series = [(names[i] if i < len(names) and names[i] else n, x, y) for i, (n, x, y) in enumerate(series)]
    return E.Session(fraction_state(series, eq, fmt, styles))
