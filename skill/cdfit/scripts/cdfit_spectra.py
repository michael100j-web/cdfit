"""Many spectra at once, as on the CD Fit page (artifact/src/spectra.js): one row per spectrum, and θ at a
wavelength against the temperature in each spectrum's name. Reading the files is in cdfit_files."""
from __future__ import annotations

import math
import os
import re

import cdfit_engine as E

_RE_TEMP = re.compile(r"(-?[0-9]+(?:[.,][0-9]+)?)\s*(?:°\s*C|℃|deg\s*C|C)(?![A-Za-z])", re.I)
_RE_NUM = re.compile(r"-?[0-9]+(?:[.,][0-9]+)?")
_RE_BARE = re.compile(r"^\s*-?[0-9]+(?:[.,][0-9]+)?\s*$")
_EDGES = re.compile(r"^[\s_\-–,;:()\[\]]+|[\s_\-–,;:()\[\]]+$")


def label_of(name):
    """The temperature (or else the last number) in a spectrum's name, and the name without it (the peptide)."""
    m = _RE_TEMP.search(name)
    celsius = bool(m)
    if m:
        number, start, end = m.group(1), m.start(), m.end()
    else:
        found = list(_RE_NUM.finditer(name))
        if not found:
            return None
        m = found[-1]
        number, start, end = m.group(0), m.start(), m.end()
    rest = re.sub(r"\(\s*\)|\[\s*\]", " ", name[:start] + name[end:])
    group = _EDGES.sub("", rest).strip()
    value = float(number.replace(",", "."))
    if not celsius and _RE_BARE.match(name) and -30 <= value <= 130:
        celsius = True   # a bare number heading a spectrum, as in a table of spectra, is its temperature
    return {"value": value, "celsius": celsius, "group": group or "Spectra"}


def value_at(ser, lam):
    order = sorted(range(len(ser["xs"])), key=lambda i: ser["xs"][i])
    for k in range(len(order) - 1):
        i, j = order[k], order[k + 1]
        x0, x1 = ser["xs"][i], ser["xs"][j]
        if x0 <= lam <= x1:
            return ser["ys"][i] + (lam - x0) / (x1 - x0) * (ser["ys"][j] - ser["ys"][i]) if x1 != x0 else ser["ys"][i]
    return math.nan


def analyse(session, lam=225.0):
    rows = []
    for ser in session.data["series"]:
        cfg = session.S["series"][ser["idx"]]
        if not cfg.get("visible") or not ser["xs"]:
            continue
        rows.append({"name": ser["name"], "label": label_of(ser["name"]), "bands": E.bands(ser), "at": value_at(ser, lam)})
    labelled = [r for r in rows if r["label"]]
    groups = {}
    for r in labelled:
        groups.setdefault(r["label"]["group"], []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["label"]["value"])
    trend = len(labelled) >= 3 and any(len({r["label"]["value"] for r in g}) >= 2 for g in groups.values())
    celsius = bool(labelled) and all(r["label"]["celsius"] for r in labelled)
    return {"lam": lam, "rows": rows, "groups": groups, "trend": trend, "celsius": celsius}


def table(v):
    head = ["Spectrum", "T (°C)" if v["celsius"] else "Number in name", "λ max (nm)", "Value at max", "λ min (nm)",
            "Value at min", "Crossover (nm)", "Rpn", f"Value at {E.fmt_num(v['lam'], 4)} nm"]
    out = [head]
    for r in v["rows"]:
        b = r["bands"]
        out.append([r["name"], E.fmt_num(r["label"]["value"], 4) if r["label"] else "—",
                    E.fmt_num(b["xMax"], 5) if b["hasPos"] else "—", E.fmt_num(b["yMax"], 4), E.fmt_num(b["xMin"], 5),
                    E.fmt_num(b["yMin"], 4), E.js_to_fixed(b["cross"], 1) if math.isfinite(b["cross"]) else "—",
                    E.js_to_fixed(b["rpn"], 3) if math.isfinite(b["rpn"]) else "—", E.fmt_num(r["at"], 4)])
    return out


def melt_table(v):
    """θ at the wavelength against temperature, one column per peptide, ready for `fit --mode melt`."""
    names = list(v["groups"])
    temps = sorted({r["label"]["value"] for n in names for r in v["groups"][n]})
    lines = ["\t".join(["T (°C)" if v["celsius"] else "X", *names])]
    for t in temps:
        cells = []
        for n in names:
            r = next((q for q in v["groups"][n] if q["label"]["value"] == t), None)
            cells.append(E.js_str(float(E.js_to_precision(r["at"], 8))) if r and math.isfinite(r["at"]) else "")
        lines.append("\t".join([E.js_str(t), *cells]))
    return "\n".join(lines)


# ---------------------------------------------------------------- output names
def common_stem(paths):
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    prefix = os.path.commonprefix(stems)
    prefix = re.sub(r"[\s_\-.,;]+$", "", prefix)
    return prefix or "merged"
