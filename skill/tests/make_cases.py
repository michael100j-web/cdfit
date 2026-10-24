"""Writes cases.json: synthetic data sets and settings that exercise every branch of the fitter.

The same states are run through the add-in in a browser (see README in this folder) to give
golden.json, which test_parity.py compares against the Python port. All data are synthetic.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cdfit", "scripts"))
import cdfit_engine as E  # noqa: E402

CMP = E.PRESETS["cmp"]["text"]
rng = np.random.default_rng(20261003)


def table(xs, cols, names, xname="T (°C)", fmt="{:.4f}", sep="\t", comma=False):
    lines = [sep.join([xname, *names])]
    for i, x in enumerate(xs):
        cells = [f"{x:g}"] + [fmt.format(c[i]) for c in cols]
        if comma:
            cells = [c.replace(".", ",") for c in cells]
        lines.append(sep.join(cells))
    return "\n".join(lines)


def cmp_curve(T, tm, refu, deu, refn, den, conc=0.0002, H=-500000.0):
    text = CMP.replace("0.0002", E.js_str(conc)).replace("H=-500000", "H=" + E.js_str(H))
    return E.compile_model(text).fn(T, [tm, refu, deu, refn, den])


def state(mode, data, **kw):
    s = E.base_state(mode)
    s["dataText"] = data
    s.update(kw)
    return s


cases = {}

# 1-3. the add-in's own example data
for mode in ("melt", "uv", "spec"):
    cases[f"example_{mode}"] = state(mode, E.example_data(mode))

# 4. UV melt with a falling feature in the baseline that the unconstrained fit takes for the transition
T = np.arange(15.0, 81.0, 1.0)
drift = 0.62 + 0.0004 * (T - 15) - 0.02 / (1 + np.exp(-(T - 62) / 2.5))
uv = drift + 0.008 / (1 + np.exp(-(T - 41) / 2.2)) + np.random.default_rng(11).normal(0, 0.0010, T.size)
cases["uv_drift"] = state("uv", table(T, [uv], ["ABC mix"]))

# 5. the same data with the constraint off (plain fit)
cases["uv_drift_any"] = state("uv", table(T, [uv], ["ABC mix"]), stepDir="any")

# 6. a CD-like falling transition fitted with "rises on unfolding": no allowed step
T = np.arange(5.0, 71.0, 1.5)
cd = cmp_curve(T, 38.0, 30.0, -0.09, 14.0, -0.004) + rng.normal(0, 0.06, T.size)
cases["cd_wrong_direction"] = state("melt", table(T, [cd], ["CMP-3"], fmt="{:.3f}"), stepDir="up")

# 7. CD melt with "falls on unfolding" (the plain fit is already allowed)
cases["cd_down"] = state("melt", table(T, [cd], ["CMP-3"], fmt="{:.3f}"), stepDir="down")

# 8. two-state preset with H fitted, three columns, one hidden, one renamed
T = np.arange(10.0, 90.5, 2.0)
two = E.compile_model(E.PRESETS["twostate"]["text"])
c1 = two.fn(T, [-250000.0, 50.0, 40.0, -0.1, -10.0, 0.08]) + rng.normal(0, 0.05, T.size)
c2 = two.fn(T, [-180000.0, 58.0, 38.0, -0.09, -12.0, 0.085]) + rng.normal(0, 0.05, T.size)
c3 = two.fn(T, [-300000.0, 44.0, 41.0, -0.1, -9.0, 0.08]) + rng.normal(0, 0.05, T.size)
cases["twostate_three"] = state(
    "melt", table(T, [c1, c2, c3], ["P1", "P2", "P3"], fmt="{:.3f}"), eqText=E.PRESETS["twostate"]["text"],
    series=[{"color": "#0a0ac8", "visible": True, "name": ""},
            {"color": "#d11a1a", "visible": False, "name": ""},
            {"color": "#16923a", "visible": True, "name": "Peptide 3"}])

# 9. Boltzmann sigmoid, decimal commas, semicolons
x = np.linspace(-3, 9, 40)
yb = 2.0 + 5.0 / (1 + np.exp((3.2 - x) / 0.9)) + rng.normal(0, 0.05, x.size)
cases["boltz_semicolon_comma"] = state("melt", table(x, [yb], ["signal"], xname="dose", sep=";", comma=True,
                                                    fmt="{:.3f}"),
                                       eqText=E.PRESETS["boltz"]["text"])

# 10. CMP fit with a start value, a fixed parameter, an excluded range and a Y multiplier
T = np.arange(4.0, 76.0, 2.0)
cd2 = (cmp_curve(T, 45.0, 32.0, -0.095, 15.0, -0.005) + rng.normal(0, 0.05, T.size)) * 1000
cases["cmp_options"] = state("melt", table(T, [cd2], ["mdeg-ish"], fmt="{:.1f}"), yMult="0.001", xFrom="8",
                             xTo="70", params={"tm": {"value": "40", "fixed": False},
                                               "den": {"value": "-0.005", "fixed": True}})

# 11. space-separated, decimal commas, no header, irregular spacing and a missing value
T = np.arange(20.0, 71.0, 2.5)
cd3 = cmp_curve(T, 51.0, 28.0, -0.08, 12.5, -0.004, conc=5e-5) + rng.normal(0, 0.05, T.size)
rows = [f"{t:.1f}   {v:.3f}".replace(".", ",") for t, v in zip(T, cd3)]
rows[5] = rows[5].split()[0]          # one temperature with no reading
cases["space_comma_noheader"] = state("melt", "\n".join(rows),
                                      eqText=CMP.replace("0.0002", "0.00005"))

# 12. custom equation with ^, functions, a constant and a comment
x = np.linspace(0.5, 20, 30)
yc = 3.0 * np.exp(-x / 4.0) + 0.5 * np.sqrt(x) + rng.normal(0, 0.02, x.size)
cases["custom_equation"] = state("melt", table(x, [yc], ["decay"], xname="t", fmt="{:.4f}"),
                                 eqText="; custom\nB=0.5\nY=A*EXP(-X/T0)+B*X^(1/2)+C*0",
                                 params={"t0": {"value": "2", "fixed": False}})

# 13. too few points for the free parameters
cases["too_few_points"] = state("melt", "T\tY\n10\t1\n20\t2\n30\t3\n40\t4\n")

# 14. a syntax error in the equation
cases["model_error"] = state("melt", E.example_data("melt"), eqText="Y=A*(X+")

# 15. Tm fixed with a direction constraint
cases["tm_fixed_up"] = state("uv", E.example_data("uv"), params={"tm": {"value": "42", "fixed": True}})

# 16. UV melt, Tm fixed outside the data, direction up: error
cases["tm_fixed_outside"] = state("uv", E.example_data("uv"), params={"tm": {"value": "95", "fixed": True}})

with open(os.path.join(HERE, "cases.json"), "w", encoding="utf-8") as f:
    json.dump(cases, f, ensure_ascii=False, indent=1)
print(f"{len(cases)} cases written")
for name, st in cases.items():
    s = E.Session(st)
    fits = [("ERR " + f["error"]) if f and f.get("error") else
            (f"Tm={E.param_value(f, s.model, 'Tm')['v']:.3f}" if f and s.model and 'tm' in s.model.keys else
             ("fit" if f else "-")) for f in s.fits]
    flags = [k for f in s.fits if f and not f.get("error") for k in ("avoided", "limit") if f.get(k)]
    print(f"  {name:24s} {s.model_error or ''} {fits} {flags}")
