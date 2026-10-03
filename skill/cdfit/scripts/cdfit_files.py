"""Files from the spectrometers, read as on the CD Fit page (artifact/src/import.js), so both give the same table.

A JASCO export keeps its CD channel. A Chirascan (Pro-Data) CSV keeps its CircularDichroism block, or its
Absorbance block in UV melting. From a scan at several wavelengths, or from spectra named with their temperatures,
the melting modes take the signal at one wavelength (225 nm unless changed) against temperature, and spectrum mode
takes one spectrum per temperature. Several files become one table, matched by X."""
from __future__ import annotations

import math
import re

import cdfit_engine as E
import cdfit_spectra as SP

HT = re.compile(r"\b(?:HT|HV)\b|volt|dynode", re.I | re.A)   # detector voltage channels, not signal
WAVE_HINT = re.compile(r"nm\b|nanomet|wave\s*length|λ", re.I)
TEMP_HINT = re.compile(r"temp|°\s*C|℃|celsius|kelvin|^\s*T\s*(?:[(\[]|$)", re.I)
TIME_HINT = re.compile(r"time|\bmin\b|\bsec|\(s\)|\[s\]", re.I | re.A)
_NM = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*nm(?![a-z])", re.I)
_CHANNEL_NM = re.compile(r"^(?:CD|θ|theta|ellipticity|abs|absorbance|A|OD)\s*[@_=:-]?\s*([0-9]{3}(?:[.,][0-9]+)?)$", re.I)
_EDGES = re.compile(r"^[\s_\-–,;:@=]+|[\s_\-–,;:@=]+$")
_CHANNEL_ONLY = re.compile(r"^(?:CD|θ|theta|ellipticity|signal|abs|absorbance|A|OD|mdeg)?\s*(?:\[[^\]]*\]|\([^)]*\))?$", re.I)
nan = math.nan


def _at(row, k):
    return row[k] if 0 <= k < len(row) else nan


def _fin(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def _cells_of(line):
    """One line's cells, split the way parse_data splits a whole table."""
    if "\t" in line:
        return line.split("\t")
    if ";" in line:
        return line.split(";")
    if re.search(r"[0-9],[0-9]", line) and re.search(r"\s", E.js_trim(line)):
        return re.split(r"\s+", E.js_trim(line))
    return re.split(r"[\s,]+", E.js_trim(line))


def csv_to_tabs(text):
    """A comma-separated file as tab-separated, so that names with spaces ("CD 225 nm") stay whole."""
    if re.search(r"[\t;]", text):
        return text
    lines = text.replace("\r", "").split("\n")
    data = [l for l in lines if re.match(r"^\s*[-+]?\.?[0-9]", l)]
    if not data or not all("," in l and not re.search(r"\S\s+\S", re.sub(r"\s*,\s*", ",", E.js_trim(l))) for l in data):
        return text
    return "\n".join("\t".join(_split_csv(l)) for l in lines)


def _split_csv(line):
    out, cur, quoted, i = [], "", False, 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch != '"':
                cur += ch
            elif line[i + 1:i + 2] == '"':
                cur += '"'
                i += 1
            else:
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == ",":
            out.append(E.js_trim(cur))
            cur = ""
        else:
            cur += ch
        i += 1
    out.append(E.js_trim(cur))
    return out


# ---------------------------------------------------------------- the instruments' files
def jasco(text):
    """A JASCO text export as a plain table: header lines, XYDATA, the data, then an extended-information block. An
    export of spectra at several temperatures starts its data with a row of temperatures under an empty first cell.
    Returns {"text", "matrix"} or None."""
    lines = text.replace("\r", "").split("\n")
    start = next((i for i, l in enumerate(lines) if E.js_trim(l).upper() == "XYDATA"), None)
    if start is None:
        return None
    head = {}
    for l in lines[:start]:
        m = re.match(r"^([^\t,;]+)[\t,;](.*)$", l)
        if m:
            head[E.js_trim(m.group(1)).upper()] = E.js_trim(m.group(2))
    data, cols = [], None
    for l in lines[start + 1:]:
        if not E.js_trim(l):
            continue
        if not data and cols is None and re.match(r"[\t,;]", l):
            c = [s for s in (E.js_trim(s) for s in re.split(r"[\t,;]", l)[1:]) if s != ""]
            if c and all(_fin(E.parse_num(s)) for s in c):
                cols = c
                continue
        cells = _cells_of(E.js_trim(l))
        if math.isnan(E.parse_num(cells[0])):
            break
        data.append("\t".join(E.js_trim(s) for s in cells))
    x = head.get("XUNITS") or "X"
    x_wave = bool(WAVE_HINT.search(x))

    def temp(c):   # spectra under their temperatures
        v = E.parse_num(c)
        return c + " °C" if x_wave and -30 <= v <= 130 else c
    names = [x, *map(temp, cols)] if cols else \
        [x, head.get("YUNITS") or "Y"] + [head[k] for k in ("Y2UNITS", "Y3UNITS") if head.get(k)]
    return {"text": "\n".join(["\t".join(names)] + data), "matrix": cols is not None}


def chirascan(text):
    """A Chirascan (Applied Photophysics Pro-Data) CSV: "ProDataCSV", remarks such as "#Concentration: 200 uM", then
    after "Data:" one block per property (CircularDichroism, HV, Absorbance, ...). A spectrum block is "Wavelength,",
    the property name, then wavelength,value rows. A scan block is the property name, "Temperature,Wavelength", a
    row of wavelengths under an empty first cell, then one row per temperature. Returns None for other files."""
    lines = text.replace("\r", "").split("\n")
    first = next((l for l in lines if E.js_trim(l)), "")
    if E.js_trim(re.sub(r"[,;\s]+$", "", first)) != "ProDataCSV":
        return None
    sep = ";" if re.search(r"^\s*-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?\s*;", text, re.M) else ","

    def remark(key):
        k = "#" + key.lower() + ":"
        line = next((s for s in lines if E.js_trim(s).lower().startswith(k)), None)
        return E.js_trim(re.sub(r"[,;\s]+$", "", E.js_trim(line)[len(key) + 2:])) if line is not None else ""

    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*data\s*:?[\s,;]*$", l, re.I)), -1)
    blocks, labels, cur = [], [], None

    def close():
        nonlocal cur
        if cur and cur["rows"]:
            blocks.append(cur)
        cur = None

    for line in lines[start + 1:]:
        cells = [E.js_trim(c) for c in line.split(sep)]
        while cells and cells[-1] == "":
            cells.pop()
        if not cells:
            close()
            continue
        nums = [E.parse_num(c) for c in cells]
        rest = nums[1:]
        numeric = bool(rest) and any(_fin(v) for v in rest) and all(c == "" or _fin(rest[k]) for k, c in enumerate(cells[1:]))
        if numeric and (cells[0] == "" or _fin(nums[0])):
            if cur is None:   # the text lines just above the numbers name the block
                prop = ([l for l in labels if sep not in l] or [""])[-1]
                axes = [a for a in (E.js_trim(c) for c in ([l for l in labels if sep in l] or [""])[-1].split(sep)) if a]
                cur = {"property": prop, "rowAxis": axes[0] if axes else "", "colAxis": axes[1] if len(axes) > 1 else "",
                       "cols": None, "rows": []}
                labels = []
            if cells[0] == "":
                cur["cols"] = rest
            else:
                cur["rows"].append(nums)
            continue
        close()
        if re.match(r"^history\s*:", cells[0], re.I):
            break
        labels.append(E.js_trim(line))
    close()
    if not blocks:
        return None
    t = re.search(r"-?[0-9]+(?:[.,][0-9]+)?", remark("Temperature"))
    return {"blocks": blocks, "description": remark("Description"), "temperature": E.parse_num(t.group(0)) if t else nan}


# ---------------------------------------------------------------- wavelengths in a table
def nm_in(name):
    """A wavelength in a column name: "225", "225 nm", "CD 225nm", "CD225", "A280"."""
    s = E.js_trim(str(name))
    m = _NM.search(s)
    if m:
        return {"w": E.parse_num(m.group(1)), "explicit": True, "at": m.start(), "len": len(m.group(0))}
    m = _CHANNEL_NM.match(s)
    if m:
        return {"w": E.parse_num(m.group(1)), "explicit": True, "at": len(s) - len(m.group(1)), "len": len(m.group(1))}
    v = E.parse_num(s)
    return {"w": v, "explicit": False, "at": 0, "len": len(s)} if _fin(v) else None


def group_of(name, hit):
    """The name without its wavelength, or "" when only a channel word (CD, A, θ, a unit) is left."""
    s = E.js_trim(str(name))
    rest = E.js_trim(_EDGES.sub("", s[:hit["at"]] + s[hit["at"] + hit["len"]:]))
    return "" if _CHANNEL_ONLY.match(rest) else rest


def wave_axis(v, hinted):
    """A wavelength axis: strictly monotonic, in the UV or visible; unlabelled numbers must look like a far-UV
    spectrum."""
    if len(v) < 2:
        return False
    up = v[1] > v[0]
    lo, hi, step = math.inf, -math.inf, 0.0
    for i, x in enumerate(v):
        if not _fin(x):
            return False
        if i and not (x > v[i - 1] if up else x < v[i - 1]):
            return False
        if i:
            step = max(step, abs(x - v[i - 1]))
        lo, hi = min(lo, x), max(hi, x)
    if lo < 150 or hi > 1100:
        return False
    return hinted or (len(v) >= 5 and lo < 250 and step <= 10)


def pick_wave(waves, lam, single=True):
    """Where the wavelength is in a scan: measured, between two wavelengths at most 5 nm apart, or the only one."""
    for k, w in enumerate(waves):
        if abs(w - lam) < 1e-6:
            return {"k": k}
    lo = hi = -1
    for i, w in enumerate(waves):
        if w < lam and (lo < 0 or w > waves[lo]):
            lo = i
        if w > lam and (hi < 0 or w < waves[hi]):
            hi = i
    if lo >= 0 and hi >= 0 and waves[hi] - waves[lo] <= 5:
        return {"lo": lo, "hi": hi, "u": (lam - waves[lo]) / (waves[hi] - waves[lo])}
    return {"k": 0, "only": True} if single and len(waves) == 1 else None


def value_of(row, pk):
    if "lo" not in pk:
        return _at(row, pk["k"])
    a, b = _at(row, pk["lo"]), _at(row, pk["hi"])
    return a + pk["u"] * (b - a)


def wave_list(waves):
    w = sorted(set(waves))
    steps = [w[i + 1] - w[i] for i in range(len(w) - 1)]
    if len(w) >= 3 and all(abs(s - steps[0]) < 1e-6 for s in steps):
        return f"{E.fmt_num(w[0], 4)}–{E.fmt_num(w[-1], 4)} nm every {E.fmt_num(steps[0], 3)} nm"
    return ", ".join(E.fmt_num(x, 4) for x in w) + " nm"


# ---------------------------------------------------------------- what a file holds
def describe(raw, stem, mode, lam):
    """What a file holds, for one mode. kind "scan": a signal at one or more wavelengths (across) against temperature
    (down); "spec": spectra, wavelengths down the first column; "melt": a melting curve; "table": anything else, used
    as it is; "none": nothing for this mode. None when the file has no numbers."""
    c = chirascan(raw)
    if c:
        return _from_chirascan(c, stem, mode)
    j = jasco(raw)
    text = j["text"] if j else csv_to_tabs(raw)
    p = E.parse_data(text)
    if not p["rows"] or not p["names"]:
        return None
    only_first = bool(j) and not j["matrix"]
    return {"file": stem, "name": stem, "source": "JASCO" if j else "", "p": p, "onlyFirst": only_first, "raw": text,
            "unit": "", **layout(p, only_first, lam)}


def layout(p, only_first, lam):
    xs = [r[0] for r in p["rows"]]
    x_name = p["xName"]
    if not TEMP_HINT.search(x_name) and not TIME_HINT.search(x_name) and wave_axis(xs, bool(WAVE_HINT.search(x_name))):
        return {"kind": "spec"}
    if only_first:
        return {"kind": "table"}
    signal = [(name, j) for j, name in enumerate(p["names"]) if not HT.search(name)]
    hits = [(name, j, h) for name, j in signal for h in [nm_in(name)] if h and 150 <= h["w"] <= 1100]
    temp_hint = bool(TEMP_HINT.search(x_name)) or x_name == ""
    if not hits or len(hits) != len(signal) or not (temp_hint or all(-30 <= x <= 130 for x in xs)):
        return {"kind": "table"}
    explicit = any(h["explicit"] for _, _, h in hits)
    groups = {}
    for name, j, h in hits:
        groups.setdefault(group_of(name, h), []).append((j, h["w"]))
    groups = [{"name": g, "waves": [w for _, w in cs], "js": [j for j, _ in cs]} for g, cs in groups.items()]
    if any(len(set(g["waves"])) != len(g["waves"]) for g in groups):
        return {"kind": "table"}
    # bare numbers count as wavelengths only under a temperature column and when the wavelength is among them
    if not explicit and not (temp_hint and any(pick_wave(g["waves"], lam, False) for g in groups)):
        return {"kind": "table"}
    return {"kind": "scan", "temps": xs,
            "groups": [{"name": g["name"], "waves": g["waves"], "rows": [[r[j + 1] for j in g["js"]] for r in p["rows"]]}
                       for g in groups]}


def _from_chirascan(c, stem, mode):
    want = re.compile(r"^absorbance$", re.I) if mode == "uv" else re.compile(r"circular\s*dichroism|^CD$", re.I)
    b = next((x for x in c["blocks"] if want.search(x["property"])), None)
    name = stem   # the file's name: the #Description remark is often left from an earlier sample
    base = {"file": stem, "name": name, "source": "Chirascan",
            "unit": "mdeg" if b and re.search("circular", b["property"], re.I) else ""}
    if not b:
        return {**base, "kind": "none", "why": "no absorbance in the file" if mode == "uv" else "no CD in the file"}
    row_wave, row_temp = bool(re.search("wave", b["rowAxis"], re.I)), bool(re.search("temp", b["rowAxis"], re.I))
    col_wave, col_temp = bool(re.search("wave", b["colAxis"], re.I)), bool(re.search("temp", b["colAxis"], re.I))
    if b["cols"] is None:
        pts = [(r[0], _at(r, 1)) for r in b["rows"]]
        if row_wave:
            t = c["temperature"]
            return {**base, "kind": "spec", "spectra": [{"name": f"{name} ({E.js_str(t)} °C)" if _fin(t) else name, "pts": pts}]}
        return {**base, "kind": "melt" if row_temp else "table", "cols": [{"name": name, "pts": pts}]}
    if row_temp and col_wave:
        return {**base, "kind": "scan", "temps": [r[0] for r in b["rows"]],
                "groups": [{"name": "", "waves": b["cols"], "rows": [r[1:] for r in b["rows"]]}]}

    def across(label):
        return [{"name": label(v), "pts": [(r[0], _at(r, k + 1)) for r in b["rows"]]} for k, v in enumerate(b["cols"])]
    if row_wave and col_temp:
        return {**base, "kind": "spec", "spectra": across(lambda t: f"{name} {E.js_str(t)} °C")}
    return {**base, "kind": "table", "cols": across(lambda v: f"{name} {E.js_str(v)}")}


# ---------------------------------------------------------------- columns for a mode
def plain_cols(fd, many):
    """A plain or JASCO file's columns, named as they always were: by the file when it gives one column."""
    p = fd["p"]
    names = p["names"]
    ny = min(1, len(names)) if fd["onlyFirst"] else len(names)
    out = []
    for j in range(ny):
        if fd["kind"] == "spec" and HT.search(names[j]) and not fd["onlyFirst"]:
            continue
        name = (fd["file"] if ny == 1 else f"{fd['file']}: {names[j]}") if (many or fd["source"]) else names[j]
        out.append({"name": name, "pts": [(r[0], r[j + 1]) for r in p["rows"] if _fin(r[j + 1])]})
    return out


def _group_name(fd, g, many):
    if not g["name"]:
        return fd["name"]
    return f"{fd['name']}: {g['name']}" if many or fd["source"] else g["name"]


def scan_melt(fd, lam, many):
    cols, notes, misses = [], [], []
    for g in fd["groups"]:
        pk, name = pick_wave(g["waves"], lam), _group_name(fd, g, many)
        if not pk:
            misses.append(g)
            continue
        cols.append({"name": name, "pts": [(t, value_of(g["rows"][i], pk)) for i, t in enumerate(fd["temps"])]})
        if pk.get("only") and abs(g["waves"][0] - lam) > 1e-6:
            notes.append(f"{name}: measured at {E.fmt_num(g['waves'][0], 4)} nm only, so that is used.")
    why = f"no {E.fmt_num(lam, 4)} nm: measured at {wave_list(misses[0]['waves'])}" if misses else ""
    if cols and misses:
        notes.append(f"{fd['file']}: {why}.")
    return {"cols": cols, "notes": notes, "why": why}


def scan_spectra(fd, many):
    out = []
    for i, t in enumerate(fd["temps"]):
        for g in fd["groups"]:
            out.append({"name": f"{_group_name(fd, g, many)} {E.js_str(t)} °C",
                        "pts": [(w, _at(g["rows"][i], k)) for k, w in enumerate(g["waves"])]})
    return out


def spectra_melt(spectra, lam):
    """Spectra from all files together (a peptide's spectra can come from several files): one column per peptide."""
    groups, labelled = {}, 0
    for s in spectra:
        lab = SP.label_of(s["name"])
        if not lab or not _fin(lab["value"]):
            continue
        labelled += 1
        v = SP.value_at({"xs": [q[0] for q in s["pts"]], "ys": [q[1] for q in s["pts"]]}, lam)
        g = groups.setdefault(lab["group"], {})
        g.setdefault(lab["value"], v)   # the first spectrum at a temperature counts
    if not (labelled >= 3 and any(len(g) >= 2 for g in groups.values())):
        return {"cols": [], "why": "spectra with no temperature series in their names"}
    cols = [{"name": n, "pts": sorted(g.items(), key=lambda q: q[0])} for n, g in groups.items()]
    cols = [c for c in cols if any(_fin(q[1]) for q in c["pts"])]
    return {"cols": cols, "why": ""} if cols else {"cols": cols, "why": f"{E.fmt_num(lam, 4)} nm is outside the spectra"}


def build(texts, mode, lam):
    """Everything the files [(stem, raw text)] give in one mode."""
    out = {"mode": mode, "cols": [], "notes": [], "skipped": [], "used": [], "picked": False, "asIs": True,
           "single": None, "scans": []}
    fds = []
    for stem, raw in texts:
        fd = describe(raw, stem, mode, lam)
        if fd:
            fds.append(fd)
        else:
            out["skipped"].append(f"{stem} (no numbers)")
    many, spectra = len(fds) > 1, []

    def use(fd, cols):
        out["cols"].extend(cols)
        out["used"].append(fd)

    for fd in fds:
        kind = fd["kind"]
        if kind == "none":
            out["skipped"].append(f"{fd['file']} ({fd['why']})")
        elif kind == "table":
            use(fd, fd.get("cols") or plain_cols(fd, many))
            if fd["source"]:
                out["asIs"] = False
        elif kind == "melt":
            if mode == "spec":
                out["skipped"].append(f"{fd['file']} (a melting curve: open it in CD melting)")
                continue
            use(fd, fd["cols"])
            out["asIs"] = False
        elif kind == "scan":
            out["asIs"] = False
            if mode == "spec":
                if any(len(g["waves"]) >= 10 for g in fd["groups"]):
                    use(fd, scan_spectra(fd, many))
                else:
                    out["skipped"].append(f"{fd['file']} (a melting scan at {wave_list(fd['groups'][0]['waves'])}: "
                                          "open it in CD melting)")
                continue
            r = scan_melt(fd, lam, many)
            out["notes"].extend(r["notes"])
            if not r["cols"]:
                out["skipped"].append(f"{fd['file']} ({r['why']})")
                continue
            use(fd, r["cols"])
            out["picked"] = True
            out["scans"].append(fd)
        else:   # spectra
            named = fd.get("spectra") or plain_cols(fd, many)
            if fd["source"]:
                out["asIs"] = False
            if mode == "spec":
                use(fd, named)
            else:
                spectra.extend({**s, "fd": fd} for s in named)
    if spectra:
        r = spectra_melt(spectra, lam)
        sources = []
        for s in spectra:
            if not any(s["fd"] is f for f in sources):
                sources.append(s["fd"])
        if r["cols"]:
            out["cols"].extend(r["cols"])
            out["used"].extend(sources)
            out["asIs"] = False
            out["picked"] = True
        else:
            for fd in sources:
                out["skipped"].append(f"{fd['file']} ({r['why']}: open {'them' if len(sources) > 1 else 'it'} in CD spectrum)")
    if len(fds) == 1 and len(out["used"]) == 1 and out["asIs"] and not fds[0]["source"]:
        out["single"] = fds[0]["raw"]
    out["unit"] = "mdeg" if out["used"] and all(fd.get("unit") == "mdeg" for fd in out["used"]) else ""
    return out


def table(x_name, cols):
    """One table from columns, matched by X; the same name twice gets a number."""
    xs, maps, names, seen = {}, [], [], {}
    for c in cols:
        m = {}
        for x, y in c["pts"]:
            if _fin(x) and _fin(y):
                k = E.js_round(x * 1e6) / 1e6
                m[k] = y
                xs[k] = x
        maps.append(m)
    for c in cols:
        n = re.sub(r"[\t\r\n]+", " ", c["name"])
        seen[n] = seen.get(n, 0) + 1
        names.append(f"{n} ({seen[n]})" if seen[n] > 1 else n)
    lines = ["\t".join([x_name, *names])]
    for k in sorted(xs):
        lines.append("\t".join([E.js_str(xs[k]), *[E.js_str(m[k]) if k in m else "" for m in maps]]))
    return "\n".join(lines)


def x_name_for(name, mode):
    if re.search(r"nanomet|^\s*λ|wavelength", name or "", re.I):
        return "λ (nm)"
    if re.search(r"temp|°c", name or "", re.I):
        return "T (°C)"
    if name and name != "X":
        return name
    return {"spec": "λ (nm)", "melt": "T (°C)", "uv": "T (°C)"}.get(mode, "X")


def plan(texts, mode, lam, switch=True):
    """The current mode if any file suits it, otherwise (with switch) the mode the files are for."""
    order = [mode] + ((["melt"] if mode == "spec" else ["spec", "melt"]) if switch else [])
    first = None
    for m in dict.fromkeys(order):
        p = build(texts, m, lam)
        if p["cols"]:
            return p
        first = first or p
    return first


def table_text(p):
    if p["single"] is not None:
        return p["single"]
    if p["asIs"]:
        fd = p["used"][0]
        x_name = x_name_for(fd["p"]["xName"] if fd.get("p") else "", p["mode"])
    else:
        x_name = "λ (nm)" if p["mode"] == "spec" else "T (°C)"
    return table(x_name, p["cols"])


def title_for(p, lam, current, mode_default):
    """The y-axis title for what was read: it follows the wavelength and the unit, unless changed by hand."""
    auto = current == mode_default or re.fullmatch(
        r"\*(?:θ|A)\*(?:_\{[\d.]+\})?(?: \((?:mdeg|10\^\{3\} deg cm\^\{2\} dmol\^\{-1\})\))?", current or "")
    if not auto:
        return current
    sub = "_{" + E.fmt_num(lam, 4) + "}"
    mode = p["mode"]
    if mode == "uv":
        return f"*A*{sub}" if p["picked"] else current
    if mode == "spec":
        return "*θ* (mdeg)" if p["unit"] == "mdeg" else current
    if p["unit"] == "mdeg":
        return f"*θ*{sub if p['picked'] else ''} (mdeg)"
    if p["picked"]:
        return re.sub(r"^\*θ\*(?:_\{[\d.]+\})?", lambda _: f"*θ*{sub}", current)
    return current


def message(p, from_mode, lam, skipped):
    """What was read, in the page's words."""
    parts, n = [], len(p["used"])
    sig = "absorbance" if p["mode"] == "uv" else "CD"
    if p["mode"] != from_mode:
        they = "they" if n > 1 else "it"
        if p["mode"] == "spec":
            parts.append(f"{'These files hold' if n > 1 else 'This file holds'} spectra, so {they} opened in CD spectrum.")
        elif from_mode == "uv":
            parts.append(f"No absorbance in {'these files' if n > 1 else 'this file'}, so {they} opened in CD melting.")
        else:
            parts.append(f"{'These files are melting scans' if n > 1 else 'This file is a melting scan'}, so {they} "
                         "opened in CD melting.")
    if p["picked"]:
        one = p["scans"][0] if len(p["scans"]) == 1 and n == 1 else None
        detail = (f" ({one['source'] + ' ' if one['source'] else ''}scan at {wave_list(one['groups'][0]['waves'])}, "
                  f"{len(one['temps'])} temperatures)") if one else ""
        who = p["used"][0]["name"] if n == 1 else f"{n} files"
        parts.append(f"{who}: {sig} at {E.fmt_num(lam, 4)} nm against temperature{detail}.")
    else:
        k = len(p["cols"])
        parts.append(f"Loaded {n} file{'s' if n > 1 else ''} as {k} data set{'s' if k > 1 else ''}.")
    parts.extend(p["notes"])
    if skipped:
        parts.append("Skipped: " + "; ".join(skipped) + ".")
    return " ".join(parts)
