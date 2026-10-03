"""Many spectra at once, as on the CD Fit page (artifact/src/spectra.js and import.js): files merged into one
table, one row per spectrum, and θ at a wavelength against the temperature in each spectrum's name."""
from __future__ import annotations

import math
import os
import re

import cdfit_engine as E

_RE_TEMP = re.compile(r"(-?[0-9]+(?:[.,][0-9]+)?)\s*(?:°\s*C|℃|deg\s*C|C)(?![A-Za-z])", re.I)
_RE_NUM = re.compile(r"-?[0-9]+(?:[.,][0-9]+)?")
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
    return {"value": float(number.replace(",", ".")), "celsius": celsius, "group": group or "Spectra"}


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


# ---------------------------------------------------------------- several files into one table
def jasco_text(text):
    """A JASCO export as a plain table (XYDATA block, column names from the units), or None."""
    lines = text.replace("\r", "").split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().upper() == "XYDATA"), None)
    if start is None:
        return None
    head = {}
    for l in lines[:start]:
        parts = re.split(r"[\t,;]", l, maxsplit=1)
        if len(parts) == 2:
            head[parts[0].strip().upper()] = parts[1].strip()
    data = []
    for l in lines[start + 1:]:
        if not l.strip():
            continue
        if math.isnan(E.parse_num(re.split(r"[\t,; ]+", l.strip())[0])):
            break
        data.append(l)
    names = [head.get("XUNITS") or "X", head.get("YUNITS") or "Y"] + [head[k] for k in ("Y2UNITS", "Y3UNITS") if head.get(k)]
    return "\n".join(["\t".join(names)] + data)


def x_name(name, mode):
    if re.search(r"nanomet|^\s*λ|wavelength", name or "", re.I):
        return "λ (nm)"
    if re.search(r"temp|°c", name or "", re.I):
        return "T (°C)"
    if name and name != "X":
        return name
    return {"spec": "λ (nm)", "melt": "T (°C)", "uv": "T (°C)"}.get(mode, "X")


def merge(parsed, mode):
    """parsed: [(file stem, parse_data result, only the first Y column)] → one table text, matched by X."""
    cols, xs = [], {}
    for stem, p, only_first in parsed:
        ny = min(1, len(p["names"])) if only_first else len(p["names"])
        for j in range(ny):
            col = {}
            for r in p["rows"]:
                v = r[j + 1]
                if math.isfinite(v):
                    k = round(r[0] * 1e6) / 1e6
                    col[k] = v
                    xs[k] = r[0]
            name = stem if ny == 1 else f"{stem}: {p['names'][j]}"
            cols.append((re.sub(r"[\t\r\n]+", " ", name), col))
    keys = sorted(xs)
    lines = ["\t".join([x_name(parsed[0][1]["xName"], mode), *[n for n, _ in cols]])]
    for k in keys:
        lines.append("\t".join([E.js_str(xs[k]), *[E.js_str(c[k]) if k in c else "" for _, c in cols]]))
    return "\n".join(lines), len(cols)


def common_stem(paths):
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    prefix = os.path.commonprefix(stems)
    prefix = re.sub(r"[\s_\-.,;]+$", "", prefix)
    return prefix or "merged"
