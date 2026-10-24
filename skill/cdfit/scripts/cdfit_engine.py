"""CD Fit engine: a Python port of the fitting code in the Word add-in (src/taskpane.html).

Data parsing, the Prism-style equation compiler, automatic starting values,
Levenberg-Marquardt, the transition-direction constraint, CD spectrum bands and
the number formatting follow the add-in line by line, so a fit here gives the
add-in's numbers. A change to one belongs in the other (see skill/tests).

Where Python and JavaScript differ (division by zero, Math.round, toFixed, the
whitespace that trim() removes), small helpers below reproduce the JavaScript
behaviour.
"""
from __future__ import annotations

import copy
import functools
import math
import re
from decimal import ROUND_HALF_UP, Decimal, localcontext

import numpy as np

ADDIN_VERSION = "1.4.2"   # add-in version this port follows

# ============================ Presets ============================
PRESETS = {
    "cmp": {
        "label": "Tm of CMPs (trimer ⇌ 3 monomers, ΔH fixed)",
        "text": """; Temp vs. Elipticity -- Tm of CMPs
; X: Temperature (°C)   Y: Ellipticity
R=8.31
H=-500000
K=EXP(H/(R*(X+273.15))*((X+273.15)/(Tm+273.15)-1)-ln(0.75*0.0002^2))
P=1/(3*K*(0.0002^2))
U=(-P/2+(P^2/4+P^3/27)^(1/2))^(1/3)
V=-(P/2+(P^2/4+P^3/27)^(1/2))^(1/3)
F= U+V+1
CDU=REFU+DEU*(X+273.15)
CDN=REFN+DEN*(X+273.15)
Y=F*(CDN-CDU)+CDU""",
    },
    "twostate": {
        "label": "Two-state unfolding, monomolecular (ΔH fitted)",
        "text": """; Monomolecular two-state transition, sloping baselines
; X: Temperature (°C)   Y: Ellipticity   H: folding enthalpy (J/mol, negative)
R=8.314
T=X+273.15
K=EXP(-H/R*(1/T-1/(Tm+273.15)))
F=K/(1+K)
CDU=REFU+DEU*T
CDN=REFN+DEN*T
Y=F*(CDN-CDU)+CDU""",
    },
    "boltz": {
        "label": "Boltzmann sigmoid",
        "text": """; Boltzmann sigmoid (Y goes from Bottom at low X to Top at high X)
Y=Bottom+(Top-Bottom)/(1+EXP((V50-X)/Slope))""",
    },
}
COLORS = ["#0a0ac8", "#d11a1a", "#16923a", "#000000", "#e07b00", "#7b2cbf", "#008b8b", "#c2185b"]
SHAPES = ["circle", "square", "triangle", "diamond", "tridown"]
TAG = "#CDFIT-STATE "
GRAPH_TITLE = "CD Fit graph #"

DEFAULT_FMT = {
    "xTitle": "*T* (°C)",
    "yTitle": "*θ*_{225} (10^{3} deg cm^{2} dmol^{-1})",
    "xMin": "", "xMax": "", "xStep": "", "xMinor": 1, "xScale": "linear",
    "yMin": "", "yMax": "", "yStep": "", "yMinor": 1, "yScale": "linear",
    "plotW": 430, "plotH": 290, "fontSize": 16, "fontFamily": "Arial",
    "markerSize": 5, "lineW": 2, "axisW": 1.25, "legend": "tr",
    "showPoints": True, "showCurve": True, "connect": False, "zeroLine": False, "curveAxis": False,
    "legendTm": True, "tmLine": False, "hollow": False,
    "exportCm": 12, "exportFmt": "png300",
}
FMT_FIELDS = ["xTitle", "yTitle", "xScale", "yScale", "xMin", "xMax", "xStep", "xMinor", "yMin", "yMax", "yStep",
              "yMinor", "plotW", "plotH", "fontSize", "fontFamily", "markerSize", "lineW", "axisW", "legend",
              "exportCm", "exportFmt"]
FMT_CHECKS = ["showPoints", "showCurve", "connect", "zeroLine", "curveAxis", "legendTm", "tmLine", "hollow"]

# ============================ Modes ============================
MODES = {
    "melt": {"label": "CD melting", "fit": True, "fmt": {}},
    "spec": {"label": "CD spectrum", "fit": False,
             "fmt": {"xTitle": "*λ* (nm)", "yTitle": "[*θ*] (10^{3} deg cm^{2} dmol^{-1})", "showPoints": False,
                     "connect": True, "zeroLine": True, "legendTm": False, "xMinor": 1}},
    "uv": {"label": "UV melting", "fit": True, "stepDir": "up", "fmt": {"yTitle": "*A*_{215}", "legend": "br"}},
}


def mode_fmt(mode):
    return {**DEFAULT_FMT, **MODES.get(mode, MODES["melt"])["fmt"]}


def base_state(mode):
    m = MODES[mode]
    return {"mode": mode, "dataText": "", "yMult": 1, "xFrom": "", "xTo": "", "series": [], "preset": "cmp",
            "eqText": PRESETS["cmp"]["text"], "params": {}, "fit": m["fit"], "stepDir": m.get("stepDir", "any"),
            "fmt": mode_fmt(mode)}


def apply_state(obj, from_graph=False):
    """The add-in's applyState: fill in defaults for the mode. from_graph is loadGraphState,
    for a state read from a graph in a document."""
    obj = copy.deepcopy(obj or {})
    mode = obj.get("mode") if obj.get("mode") in MODES else "melt"   # graphs saved before modes existed are CD melting
    if from_graph and "stepDir" not in obj:
        obj["stepDir"] = "any"   # graphs made before 1.4 keep their unconstrained fit
    S = {**base_state(mode), **obj, "mode": mode}
    S["fmt"] = {**mode_fmt(mode), **(obj.get("fmt") or {})}
    S["series"] = S.get("series") or []
    S["params"] = S.get("params") or {}
    # repair "Â°"/"Â±" left in data saved while add-in version 1.1.2 had mis-encoded text
    if isinstance(S.get("dataText"), str) and re.search("Â[°±]", S["dataText"]):
        S["dataText"] = re.sub("Â([°±])", r"\1", S["dataText"])
    return S


# ============================ JavaScript semantics ============================
JS_WS = "\t\n\v\f\r              " \
        "    　﻿"
_S = "[" + JS_WS.replace("\\", "\\\\") + "]"          # JavaScript's \s
_RE_S = re.compile(_S)
_RE_S_PLUS = re.compile(_S + "+")
_RE_S_COMMA = re.compile("(?:" + _S + "|,)+")
nan, inf = math.nan, math.inf


def js_trim(s):
    return s.strip(JS_WS)


def js_round(x):
    """Math.round: the nearest integer, halves toward +infinity."""
    if not math.isfinite(x):
        return x
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def js_div(a, b):
    with np.errstate(all="ignore"):
        return float(np.float64(a) / np.float64(b))


def js_max(a, b):
    return nan if math.isnan(a) or math.isnan(b) else max(a, b)


def js_is_finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _dec_round(x, exp10):
    """Round the exact binary value of |x| to a multiple of 10**exp10, halves up (as toFixed/toPrecision do)."""
    with localcontext() as ctx:
        ctx.prec = 400
        return Decimal(abs(x)).quantize(Decimal(1).scaleb(exp10), rounding=ROUND_HALF_UP)


def js_str(x):
    """String(number)."""
    x = float(x)
    if math.isnan(x):
        return "NaN"
    if x == 0:
        return "0"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    sign = "-" if x < 0 else ""
    t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = "".join(map(str, t.digits))
    k = len(digits)
    n = t.exponent + k
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    es = ("+" if e >= 0 else "-") + str(abs(e))
    return sign + (digits if k == 1 else digits[0] + "." + digits[1:]) + "e" + es


def js_to_fixed(x, d):
    """Number.prototype.toFixed(d)."""
    x = float(x)
    if not math.isfinite(x) or abs(x) >= 1e21:
        return js_str(x)
    q = _dec_round(x, -d)
    s = format(q, "f")
    return ("-" if x < 0 else "") + s


def _digits_exp(x, p):
    """p significant digits of |x| (halves up) and the decimal exponent of the first one."""
    d = Decimal(abs(x))
    e = d.adjusted()
    with localcontext() as ctx:
        ctx.prec = 400
        n = d.scaleb(p - 1 - e).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if n >= 10 ** p:
        e += 1
        n = Decimal(10 ** (p - 1))
    return str(int(n)), e


def js_to_precision(x, p):
    """Number.prototype.toPrecision(p)."""
    x = float(x)
    if not math.isfinite(x):
        return js_str(x)
    sign = "-" if x < 0 else ""
    if x == 0:
        digits, e = "0" * p, 0
    else:
        digits, e = _digits_exp(x, p)
    if e < -6 or e >= p:
        m = digits[0] + ("." + digits[1:] if p > 1 else "")
        return sign + m + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    if e == p - 1:
        return sign + digits
    if e >= 0:
        return sign + digits[:e + 1] + "." + digits[e + 1:]
    return sign + "0." + "0" * (-(e + 1)) + digits


def js_to_exponential(x, f):
    """Number.prototype.toExponential(f)."""
    x = float(x)
    if not math.isfinite(x):
        return js_str(x)
    sign = "-" if x < 0 else ""
    if x == 0:
        digits, e = "0" * (f + 1), 0
    else:
        digits, e = _digits_exp(x, f + 1)
    m = digits[0] + ("." + digits[1:] if f > 0 else "")
    return sign + m + "e" + ("+" if e >= 0 else "-") + str(abs(e))


_RE_PARSEFLOAT = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")
_RE_NUMBER = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z")


def js_parse_float(v):
    """parseFloat(v)."""
    if v is None or isinstance(v, bool):
        return nan
    if isinstance(v, (int, float)):
        v = js_str(v)
    m = _RE_PARSEFLOAT.match(str(v).lstrip(JS_WS))
    if not m:
        return nan
    t = m.group(0)
    if "Infinity" in t:
        return -inf if t.startswith("-") else inf
    return float(t)


def js_number(v):
    """Unary plus: +v."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = js_trim(str(v))
    if s == "":
        return 0.0
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
        return float(int(s, 16))
    if not _RE_NUMBER.match(s):
        return nan
    if "Infinity" in s:
        return -inf if s.startswith("-") else inf
    return float(s)


def _seqsum(a):
    """Left-to-right sum, as a JavaScript loop adds."""
    return float(np.cumsum(a)[-1]) if len(a) else 0.0


# ============================ Data parsing ============================
_RE_PARSENUM = re.compile(r"[-+]?([0-9]+[.,]?[0-9]*|[.,][0-9]+)([eE][-+]?[0-9]+)?")


def parse_num(s):
    s = js_trim(str(s))
    if s == "":
        return nan
    s = _RE_S.sub("", s.replace("−", "-"))
    if not _RE_PARSENUM.fullmatch(s):
        return nan
    return float(s.replace(",", ".", 1))


def parse_data(text):
    lines = [l for l in str(text).replace("\r", "").split("\n") if js_trim(l) != ""]
    if not lines:
        return {"xName": None, "names": [], "rows": []}
    if any("\t" in l for l in lines):
        split = lambda l: l.split("\t")
    elif any(";" in l for l in lines):
        split = lambda l: l.split(";")
    elif any(re.search("[0-9],[0-9]", l) and _RE_S.search(js_trim(l)) for l in lines):
        split = lambda l: _RE_S_PLUS.split(js_trim(l))   # decimal commas, space separated
    else:
        split = lambda l: _RE_S_COMMA.split(js_trim(l))
    cells = [split(l) for l in lines]
    names = None
    first = cells[0]
    if any(js_trim(c) != "" and math.isnan(parse_num(c)) for c in first[1:]) or math.isnan(parse_num(first[0])):
        names = [js_trim(c) for c in first]
        cells = cells[1:]
    ncol = max([2] + [len(r) for r in cells] + [len(names) if names else 0])
    rows = []
    for r in cells:
        o = [parse_num(r[i] if i < len(r) else "") for i in range(ncol)]
        if math.isfinite(o[0]):
            rows.append(o)
    n_series = ncol - 1
    out_names = []
    for j in range(n_series):
        nm = names[j + 1] if names and j + 1 < len(names) else ""
        out_names.append(nm or ("Data" if n_series == 1 else f"Data {j + 1}"))
    return {"xName": names[0] if names else "X", "names": out_names, "rows": rows}


def build_data(S):
    """The add-in's buildData; also aligns S['series'] with the data columns, as the add-in does."""
    p = parse_data(S.get("dataText", ""))
    mult = js_parse_float(S.get("yMult"))
    mult = mult if math.isfinite(mult) else 1
    lo = -inf if S.get("xFrom") == "" else js_parse_float(S.get("xFrom"))
    hi = inf if S.get("xTo") == "" else js_parse_float(S.get("xTo"))
    series = []
    for j, name in enumerate(p["names"]):
        xs, ys, xs_ex, ys_ex = [], [], [], []
        for r in p["rows"]:
            x, y = r[0], r[j + 1]
            if not math.isfinite(y):
                continue
            if x < lo or x > hi:
                xs_ex.append(x)
                ys_ex.append(y * mult)
            else:
                xs.append(x)
                ys.append(y * mult)
        series.append({"name": name, "xs": xs, "ys": ys, "xsEx": xs_ex, "ysEx": ys_ex})
    cfg = S.setdefault("series", [])
    while len(cfg) < len(series):
        cfg.append(None)
    for j in range(len(series)):
        if not cfg[j]:
            cfg[j] = {"color": COLORS[j % len(COLORS)], "visible": True, "name": ""}
    del cfg[len(series):]
    for j, s in enumerate(series):
        if cfg[j].get("name"):
            s["name"] = cfg[j]["name"]
        s["idx"] = j
    return {"series": series, "xName": p["xName"]}


# ============================ Equation compiler ============================
class ModelError(ValueError):
    pass


class FitError(ValueError):
    pass


def _pow(a, b):
    """The add-in's $pow: odd roots of negative numbers (e.g. ^(1/3)) return the real root."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if b.ndim == 0:   # the exact shortcuts of V8's Math.pow (fdlibm), so results match the add-in to the last bit
        bv = float(b)
        if bv == 2:
            return a * a
        if bv == 1:
            return a
        if bv == -1:
            return 1.0 / a
        if bv == 0.5:
            return np.where(a >= 0, np.sqrt(np.abs(a)), np.power(a, b))
    out = np.power(a, b)
    neg = (a < 0) & ~(np.isfinite(b) & (np.floor(b) == b))
    if np.any(neg):
        inv = 1.0 / b
        r = np.round(inv)
        odd = neg & (np.abs(inv - r) < 1e-9) & (np.abs(np.fmod(r, 2)) == 1)
        if np.any(odd):
            out = np.where(odd, -np.power(-a, b), out)
    return out


def _min(*args):
    return functools.reduce(np.minimum, args) if args else np.float64(inf)


def _max(*args):
    return functools.reduce(np.maximum, args) if args else np.float64(-inf)


FUNCS = {"exp": "_np.exp", "ln": "_np.log", "log": "_np.log10", "log10": "_np.log10", "sqrt": "_np.sqrt",
         "abs": "_np.abs", "cbrt": "_np.cbrt", "sin": "_np.sin", "cos": "_np.cos", "tan": "_np.tan",
         "atan": "_np.arctan", "min": "_min", "max": "_max", "pow": "_pow"}
CONSTS = {"pi": "_PI"}
_RE_TOK_NUM = re.compile(r"([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?")
_RE_TOK_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(src, line_no):
    toks, i = [], 0
    while i < len(src):
        c = src[i]
        if _RE_S.match(c):
            i += 1
            continue
        m = _RE_TOK_NUM.match(src, i)
        if m:
            toks.append(("num", m.group(0)))
            i = m.end()
            continue
        m = _RE_TOK_ID.match(src, i)
        if m:
            toks.append(("id", m.group(0)))
            i = m.end()
            continue
        if src.startswith("**", i):
            toks.append(("op", "^"))
            i += 2
            continue
        if c in "+-*/^(),":
            toks.append(("op", c))
            i += 1
            continue
        raise ModelError(f'Line {line_no}: unexpected character "{c}"')
    return toks


class Model:
    """A compiled equation. fn(x, p) evaluates Y on an array of X; vars(x, p) returns every defined quantity."""

    def __init__(self, params, fn, vars_fn, defs, source):
        self.params = params                     # display names, in order of first use
        self.keys = [p.lower() for p in params]
        self._fn = fn
        self._vars = vars_fn
        self.defs = defs                         # lowercased names that are defined
        self.source = source

    def fn(self, x, p):
        x = np.asarray(x, dtype=float)
        with np.errstate(all="ignore"):
            y = self._fn(x, np.asarray(p, dtype=float))
        return np.broadcast_to(np.asarray(y, dtype=float), x.shape)

    def vars(self, x, p):
        with np.errstate(all="ignore"):
            v = self._vars(np.float64(x), np.asarray(p, dtype=float))
        return {k: float(np.asarray(val, dtype=float).reshape(-1)[0]) for k, val in v.items()}


def compile_model(text):
    defs = []
    for k, raw in enumerate(str(text).replace("\r", "").split("\n")):
        line = js_trim(raw)
        if not line or line.startswith(";") or line.startswith("//") or line.startswith("#"):
            continue
        eqi = line.find("=")
        if eqi < 0:
            raise ModelError(f"Line {k + 1}: expected NAME=expression")
        name = js_trim(line[:eqi])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ModelError(f'Line {k + 1}: "{name}" is not a valid name')
        if name.lower() == "x":
            raise ModelError(f"Line {k + 1}: X cannot be redefined")
        defs.append({"name": name, "key": name.lower(), "expr": line[eqi + 1:], "line": k + 1})
    if not defs:
        raise ModelError("The equation is empty.")
    if defs[-1]["key"] != "y":
        raise ModelError("The last definition must be Y=…")
    assigned_all = {d["key"] for d in defs}
    defined = []                 # insertion-ordered set
    params, param_idx, consts, body = [], {}, [], []

    for d in defs:
        toks = tokenize(d["expr"], d["line"])
        pos = 0

        def peek():
            return toks[pos] if pos < len(toks) else None

        def eat(v):
            nonlocal pos
            t = peek()
            if not t or t[1] != v:
                raise ModelError(f'Line {d["line"]}: expected "{v}"')
            pos += 1

        def parse_expr():
            nonlocal pos
            s = parse_term()
            while peek() and peek()[1] in "+-" and peek()[0] == "op":
                op = toks[pos][1]
                pos += 1
                s = f"({s}{op}{parse_term()})"
            return s

        def parse_term():
            nonlocal pos
            s = parse_unary()
            while peek() and peek()[0] == "op" and peek()[1] in ("*", "/"):
                op = toks[pos][1]
                pos += 1
                s = f"({s}{op}{parse_unary()})"
            return s

        def parse_unary():
            nonlocal pos
            t = peek()
            if t and t[0] == "op" and t[1] == "-":
                pos += 1
                return f"(-{parse_unary()})"
            if t and t[0] == "op" and t[1] == "+":
                pos += 1
                return parse_unary()
            return parse_power()

        def parse_power():
            nonlocal pos
            base = parse_primary()
            t = peek()
            if t and t[0] == "op" and t[1] == "^":
                pos += 1
                return f"_pow({base},{parse_unary()})"
            return base

        def parse_primary():
            nonlocal pos
            t = peek()
            pos += 1
            if not t:
                raise ModelError(f'Line {d["line"]}: expression ends unexpectedly')
            if t[0] == "num":
                consts.append(np.float64(float(t[1])))
                return f"(_c[{len(consts) - 1}])"
            if t[1] == "(" and t[0] == "op":
                s = parse_expr()
                eat(")")
                return f"({s})"
            if t[0] == "id":
                key = t[1].lower()
                nt = peek()
                if nt and nt[0] == "op" and nt[1] == "(":
                    fn = FUNCS.get(key)
                    if not fn:
                        raise ModelError(f'Line {d["line"]}: unknown function {t[1]}()')
                    pos += 1
                    args = []
                    nt = peek()
                    if not (nt and nt[0] == "op" and nt[1] == ")"):
                        args.append(parse_expr())
                        while peek() and peek()[0] == "op" and peek()[1] == ",":
                            pos += 1
                            args.append(parse_expr())
                    eat(")")
                    return f"{fn}({','.join(args)})"
                if key == "x":
                    return "x"
                if key in defined:
                    return f"v_{key}"
                if key in assigned_all:
                    raise ModelError(f'Line {d["line"]}: {t[1]} is used before it is defined')
                if key in CONSTS:
                    return CONSTS[key]
                if key not in param_idx:
                    param_idx[key] = len(params)
                    params.append(t[1])
                return f"p[{param_idx[key]}]"
            raise ModelError(f'Line {d["line"]}: unexpected "{t[1]}"')

        py = parse_expr()
        if pos < len(toks):
            raise ModelError(f'Line {d["line"]}: unexpected "{toks[pos][1]}"')
        body.append(f"    v_{d['key']} = {py}")
        if d["key"] not in defined:
            defined.append(d["key"])

    if not params:
        raise ModelError("The equation has no parameters to fit.")
    ns = {"_np": np, "_pow": _pow, "_min": _min, "_max": _max, "_PI": np.float64(math.pi), "_c": consts}
    src_fn = "def _fn(x, p):\n" + "\n".join(body) + "\n    return v_y\n"
    src_vars = ("def _vars(x, p):\n" + "\n".join(body) + "\n    return {"
                + ", ".join(f"'{k}': v_{k}" for k in defined) + "}\n")
    exec(compile(src_fn, "<cdfit model>", "exec"), ns)
    exec(compile(src_vars, "<cdfit model vars>", "exec"), ns)
    return Model(params, ns["_fn"], ns["_vars"], set(defined), text)


# ============================ Initial estimates ============================
def linfit(xs, ys):
    n = len(xs)
    sx = sy = sxx = sxy = 0.0
    for i in range(n):
        sx += xs[i]
        sy += ys[i]
        sxx += xs[i] * xs[i]
        sxy += xs[i] * ys[i]
    den = n * sxx - sx * sx
    b = 0.0 if abs(den) < 1e-300 else js_div(n * sxy - sx * sy, den)
    return {"a": js_div(sy - b * sx, n), "b": b}


def estimates(xs, ys):
    idx = sorted(range(len(xs)), key=lambda i: xs[i])
    X = [xs[i] for i in idx]
    Y = [ys[i] for i in idx]
    n = len(X)
    k = max(3, min(n, js_round(n * 0.2)))
    K = lambda x: x + 273.15
    low = linfit([K(x) for x in X[:k]], Y[:k])
    high = linfit([K(x) for x in X[max(0, n - k):]], Y[max(0, n - k):])
    tm = (X[0] + X[n - 1]) / 2

    def f(i):
        yn = low["a"] + low["b"] * K(X[i])
        yu = high["a"] + high["b"] * K(X[i])
        return js_div(Y[i] - yu, yn - yu)

    for i in range(1, n):
        f0, f1 = f(i - 1), f(i)
        if (f0 - 0.5) * (f1 - 0.5) <= 0 and f0 != f1:
            tm = X[i - 1] + js_div(0.5 - f0, f1 - f0) * (X[i] - X[i - 1])
            break
    mean = lambda a: js_div(_seqsum(np.asarray(a, dtype=float)), len(a))
    return {"tm": tm, "refn": low["a"], "den": low["b"], "refu": high["a"], "deu": high["b"], "h": -300000.0,
            "bottom": mean(Y[:k]), "top": mean(Y[max(0, n - k):]), "v50": tm, "slope": (X[n - 1] - X[0]) / 15}


# ============================ Levenberg–Marquardt ============================
def _scale_of(v):
    s = math.sqrt(abs(v)) if math.isfinite(v) else (inf if math.isinf(v) else nan)
    return s if (s and not math.isnan(s)) else 1.0


def solve_scaled(A, g):
    m = len(g)
    D = [_scale_of(A[i][i]) for i in range(m)]
    M = [[js_div(A[i][j], D[i] * D[j]) for j in range(m)] + [js_div(g[i], D[i])] for i in range(m)]
    for c in range(m):
        piv = c
        for r in range(c + 1, m):
            if abs(M[r][c]) > abs(M[piv][c]):
                piv = r
        if not (abs(M[piv][c]) > 1e-14):
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(m):
            if r != c:
                f = M[r][c] / M[c][c]
                if f == f and f != 0:
                    for k in range(c, m + 1):
                        M[r][k] -= f * M[c][k]
    return [M[i][m] / M[i][i] / D[i] for i in range(m)]


def invert_scaled(A):
    m = len(A)
    D = [_scale_of(A[i][i]) for i in range(m)]
    M = [[js_div(A[i][j], D[i] * D[j]) for j in range(m)] + [1.0 if i == j else 0.0 for j in range(m)]
         for i in range(m)]
    for c in range(m):
        piv = c
        for r in range(c + 1, m):
            if abs(M[r][c]) > abs(M[piv][c]):
                piv = r
        if not (abs(M[piv][c]) > 1e-15):
            return None
        M[c], M[piv] = M[piv], M[c]
        d = M[c][c]
        for k in range(2 * m):
            M[c][k] /= d
        for r in range(m):
            if r != c:
                f = M[r][c]
                if f == f and f != 0:
                    for k in range(2 * m):
                        M[r][k] -= f * M[c][k]
    return [[js_div(M[i][m + j], D[i] * D[j]) for j in range(m)] for i in range(m)]


def t_crit_975(df):
    tab = [nan, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228]
    if df <= 10:
        return tab[df] if 0 <= df < len(tab) else nan
    z = 1.959963985
    z2 = z * z
    return (z + (z2 * z + z) / (4 * df) + (5 * z2 * z2 * z + 16 * z2 * z + 3 * z) / (96 * df * df)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * df ** 3))


def lm_fit(model, xs, ys, p0, fixed):
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    n = len(xs)
    free = [i for i in range(len(p0)) if not fixed[i]]
    m = len(free)
    if n <= m:
        raise FitError(f"Only {n} points for {m} free parameters.")

    def eval_r(p):
        y = model.fn(xs, p)
        if not np.all(np.isfinite(y)):
            return None
        r = ys - y
        return r, _seqsum(r * r)

    def jac(p, central):
        J = []
        for k in free:
            h = (6e-6 if central else 1.5e-8) * js_max(abs(p[k]), 1e-3)
            pp = p.copy()
            pp[k] += h
            if central:
                pm = p.copy()
                pm[k] -= h
                with np.errstate(all="ignore"):
                    col = (model.fn(xs, pp) - model.fn(xs, pm)) / (2 * h)
            else:
                with np.errstate(all="ignore"):
                    col = (model.fn(xs, pp) - model.fn(xs, p)) / h
            if not np.all(np.isfinite(col)):
                return None
            J.append(col)
        return J

    def normal(J, r):
        A = [[0.0] * m for _ in range(m)]
        g = []
        for a in range(m):
            g.append(_seqsum(J[a] * r))
            for b in range(a + 1):
                A[a][b] = _seqsum(J[a] * J[b])
        for a in range(m):
            for b in range(a + 1, m):
                A[a][b] = A[b][a]
        return A, g

    P = np.array(p0, dtype=float)
    cur = eval_r(P)
    if cur is None:
        raise FitError("The model gives non-numeric values at the initial parameter values.")
    lam, it, converged = 1e-3, 0, False
    while it < 400 and m > 0:
        J = jac(P, False)
        if J is None:
            raise FitError("Could not compute derivatives (the model is not finite near the current values).")
        A, g = normal(J, cur[0])
        improved = small = False
        while lam < 1e16:
            M = [[(v * (1 + lam) + 1e-300 if i == j else v) for j, v in enumerate(row)] for i, row in enumerate(A)]
            d = solve_scaled(M, g)
            if d is not None:
                Pn = P.copy()
                for j, k in enumerate(free):
                    Pn[k] += d[j]
                nw = eval_r(Pn)
                if nw is not None and nw[1] <= cur[1]:
                    rel = (cur[1] - nw[1]) / (cur[1] + 1e-300)
                    small = rel < 1e-13 or all(abs(d[j]) <= 1e-11 * (abs(P[free[j]]) + 1e-11) for j in range(m))
                    P, cur = Pn, nw
                    lam = max(lam / 10, 1e-12)
                    improved = True
                    break
            lam *= 10
        if not improved or small:
            converged = True
            break
        it += 1
    df, ssr = n - m, cur[1]
    se = [nan] * len(P)
    cov = None
    if m > 0:
        J = jac(P, True)
        if J is not None:
            A, _ = normal(J, cur[0])
            cov = invert_scaled(A)
        if cov is not None:
            for j, k in enumerate(free):
                se[k] = math.sqrt(js_max(0.0, cov[j][j]) * ssr / df)
    ybar = _seqsum(ys) / n
    sst = _seqsum((ys - ybar) ** 2)
    t = t_crit_975(df)
    Pl = [float(v) for v in P]
    return {
        "p": Pl, "se": se, "fixed": list(fixed),
        "ci": [None if fixed[i] else [Pl[i] - t * se[i], Pl[i] + t * se[i]] for i in range(len(Pl))],
        "ssr": ssr, "df": df, "n": n, "r2": 1 - ssr / sst if sst > 0 else nan, "syx": math.sqrt(ssr / df),
        "iter": it, "converged": converged, "ambiguous": cov is None,
    }


# ============================ Transition direction ============================
# The step is the unfolded minus the native baseline at the midpoint: CDU − CDN evaluated at X = Tm.
def step_supported(model):
    return bool(model) and "tm" in model.keys and "cdu" in model.defs and "cdn" in model.defs


def step_at(model, p):
    v = model.vars(p[model.keys.index("tm")], p)
    return v["cdu"] - v["cdn"]


def step_ok(model, p, direction):
    s = step_at(model, p)
    return s >= 0 if direction == "up" else s <= 0


def directed_fit(model, xs, ys, p0, fixed, direction):
    """Fit with the step held to one sign and Tm inside the data. Tm is scanned across the data with the other
    parameters refitted at each Tm; the best allowed point is refined, and the best point overall gives the
    unconstrained fit to compare against."""
    i_tm = model.keys.index("tm")
    word = "rising" if direction == "up" else "falling"
    lo, hi = min(xs), max(xs)
    inside = lambda p: lo <= p[i_tm] <= hi
    allowed = lambda p: inside(p) and math.isfinite(step_at(model, p)) and step_ok(model, p, direction)
    if fixed[i_tm]:
        r = lm_fit(model, xs, ys, p0, fixed)
        if allowed(r["p"]):
            return r
        raise FitError(f"With Tm fixed, the fit does not give a {word} step inside the data. "
                       "Free Tm or change the transition direction.")
    N = 24
    fix_tm = list(fixed)
    fix_tm[i_tm] = True
    best = best_any = None

    def try_tm(tm):
        nonlocal best, best_any
        p = list(p0)
        p[i_tm] = tm
        try:
            r = lm_fit(model, xs, ys, p, fix_tm)
            if not best_any or r["ssr"] < best_any["ssr"]:
                best_any = r
            if step_ok(model, r["p"], direction) and (not best or r["ssr"] < best["ssr"]):
                best = r
        except (FitError, ArithmeticError, ValueError):
            pass

    for k in range(N + 1):
        try_tm(lo + (hi - lo) * k / N)
    plain = None
    try:
        plain = lm_fit(model, xs, ys, best_any["p"] if best_any else p0, fixed)
    except (FitError, ArithmeticError, ValueError):
        pass
    if not best:
        raise FitError(f"No fit gives a {word} step at the transition.")
    out = None
    try:
        r = lm_fit(model, xs, ys, best["p"], fixed)
        if allowed(r["p"]):
            out = r
    except (FitError, ArithmeticError, ValueError):
        pass
    if plain and allowed(plain["p"]) and (not out or plain["ssr"] <= out["ssr"]):
        return plain
    if not out:   # the best allowed fit sits against the constraint: settle Tm by a fine scan, without a standard error
        t0, h = best["p"][i_tm], (hi - lo) / N
        for k in range(-10, 11):
            tm = t0 + h * k / 10
            if lo <= tm <= hi:
                try_tm(tm)
        out = {**best, "fixed": list(fixed), "limit": True}
        out["se"] = list(best["se"])
        out["se"][i_tm] = nan
        out["ci"] = list(best["ci"])
        out["ci"][i_tm] = [nan, nan]
    if plain and not allowed(plain["p"]):
        out["avoided"] = {"tm": plain["p"][i_tm], "syx": plain["syx"], "outside": not inside(plain["p"])}
    return out


# ============================ Fitting orchestration ============================
def run_fits(S, data, model):
    fits = []
    if not model or not data:
        return fits
    for j, s in enumerate(data["series"]):
        if not S["series"][j].get("visible") or len(s["xs"]) == 0:
            fits.append(None)
            continue
        try:
            est = estimates(s["xs"], s["ys"])
            p0, fixed = [], []
            for i, name in enumerate(model.params):
                key = model.keys[i]
                cfg = S["params"].get(key) or {"value": "", "fixed": False}
                v = js_parse_float(cfg.get("value"))
                auto = est[key] if key in est and math.isfinite(est[key]) else 1.0
                if cfg.get("fixed") and not math.isfinite(v):
                    raise FitError(f"{name} is fixed but has no value.")
                p0.append(v if math.isfinite(v) else auto)
                fixed.append(bool(cfg.get("fixed")))
            direction = S.get("stepDir") if step_supported(model) and S.get("stepDir") in ("up", "down") else None
            fit = (directed_fit(model, s["xs"], s["ys"], p0, fixed, direction) if direction
                   else lm_fit(model, s["xs"], s["ys"], p0, fixed))
            if step_supported(model):
                fit["step"] = step_at(model, fit["p"])
                fit["dir"] = direction
            fits.append(fit)
        except (FitError, ArithmeticError, ValueError) as e:
            fits.append({"error": str(e)})
    return fits


def param_value(fit, model, name):
    if not fit or fit.get("error") or not model:
        return None
    key = name.lower()
    if key not in model.keys:
        return None
    i = model.keys.index(key)
    return {"v": fit["p"][i], "se": fit["se"][i], "ci": fit["ci"][i], "fixed": fit["fixed"][i]}


# ============================ CD spectrum bands ============================
def bands(ser):
    """Positive maximum, negative minimum, zero crossing between them, Rpn = θmax/|θmin|."""
    idx = sorted(range(len(ser["xs"])), key=lambda i: ser["xs"][i])
    X = [ser["xs"][i] for i in idx]
    Y = [ser["ys"][i] for i in idx]
    if not X:
        return None
    i_max = i_min = 0
    for i, y in enumerate(Y):
        if y > Y[i_max]:
            i_max = i
        if y < Y[i_min]:
            i_min = i
    cross = nan
    a, b = (i_min, i_max) if i_min < i_max else (i_max, i_min)
    for i in range(a, b):
        if Y[i] * Y[i + 1] <= 0 and Y[i] != Y[i + 1]:
            cross = X[i] - Y[i] * (X[i + 1] - X[i]) / (Y[i + 1] - Y[i])
            break
    # a positive band must stand clearly above the noise: at least 2% of the negative band
    has_neg = Y[i_min] < 0
    has_pos = Y[i_max] > 0 and (not has_neg or Y[i_max] > 0.02 * abs(Y[i_min]))
    return {"xMax": X[i_max], "yMax": Y[i_max], "xMin": X[i_min], "yMin": Y[i_min],
            "cross": cross if has_pos else nan,
            "rpn": Y[i_max] / abs(Y[i_min]) if has_pos and has_neg else nan, "hasPos": has_pos, "n": len(X)}


# ============================ Number formatting ============================
def fmt_num(v, sig=4):
    if v is None or not js_is_finite(v):
        return "—"
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e6 or a < 1e-3:
        return js_to_exponential(v, sig - 1).replace("e", "E")
    return js_str(float(js_to_precision(v, sig)))


def decimals_for(se):
    return min(10, max(0, 1 - math.floor(math.log10(se))))


def fmt_pm(v, se):
    if not js_is_finite(se) or se <= 0:
        return fmt_num(v)
    if abs(v) >= 1e6 or abs(v) < 1e-3:
        return fmt_num(v) + " ± " + fmt_num(se, 2)
    d = decimals_for(se)
    return js_to_fixed(v, d) + " ± " + js_to_fixed(se, d)


def fmt_tick(v, step):
    d = 0
    while d < 8 and abs(js_round(step * 10 ** d) - step * 10 ** d) > 1e-6:
        d += 1
    s = js_to_fixed(0 if abs(v) < step * 1e-9 else v, d)
    return s.replace("-", "−", 1)


# ============================ A fitted session ============================
class Session:
    """One add-in state (data, model and graph settings) with its data parsed and fitted, as after refresh(true)."""

    def __init__(self, state, from_graph=False):
        self.S = apply_state(state, from_graph)
        self.refresh()

    def refresh(self):
        self.data = build_data(self.S)
        self.model = self.model_error = None
        if self.S.get("fit"):
            try:
                self.model = compile_model(self.S.get("eqText", ""))
            except ModelError as e:
                self.model_error = str(e)
        self.fits = run_fits(self.S, self.data, self.model)

    @property
    def visible(self):
        return [s for s in self.data["series"] if self.S["series"][s["idx"]].get("visible")]

    def fit_of(self, ser):
        return self.fits[ser["idx"]] if ser["idx"] < len(self.fits) else None

    def tm(self, ser):
        return param_value(self.fit_of(ser), self.model, "Tm")

    # ---- the add-in's text outputs ----
    def results_matrix(self):
        S, data, model = self.S, self.data, self.model
        if not S.get("fit"):
            cols = [s for s in data["series"] if S["series"][s["idx"]].get("visible") and s["xs"]]
            B = [bands(s) for s in cols]
            return [["Spectrum", *[s["name"] for s in cols]],
                    ["λ max (nm)", *[fmt_num(b["xMax"], 5) if b["hasPos"] else "—" for b in B]],
                    ["Value at max", *[fmt_num(b["yMax"], 4) for b in B]],
                    ["λ min (nm)", *[fmt_num(b["xMin"], 5) for b in B]],
                    ["Value at min", *[fmt_num(b["yMin"], 4) for b in B]],
                    ["Crossover (nm)", *[js_to_fixed(b["cross"], 1) if math.isfinite(b["cross"]) else "—" for b in B]],
                    ["Rpn", *[js_to_fixed(b["rpn"], 3) if math.isfinite(b["rpn"]) else "—" for b in B]]]
        if not model:
            return [["Parameter"]]
        cols = [s for s in data["series"] if S["series"][s["idx"]].get("visible") and self.fit_of(s)
                and not self.fit_of(s).get("error")]
        rows = [["Parameter", *[s["name"] for s in cols]]]
        for i, name in enumerate(model.params):
            label = "Tm (°C)" if name.lower() == "tm" else name
            row = [label]
            for s in cols:
                f = self.fit_of(s)
                row.append(fmt_num(f["p"][i]) + " (fixed)" if f["fixed"][i] else fmt_pm(f["p"][i], f["se"][i]))
            rows.append(row)
        if "tm" in model.keys:
            ti = model.keys.index("tm")
            row = ["Tm 95% CI"]
            for s in cols:
                c = self.fit_of(s)["ci"][ti]
                row.append(f"{js_to_fixed(c[0], 2)} to {js_to_fixed(c[1], 2)}" if c and math.isfinite(c[0]) else "—")
            rows.append(row)
        if any(js_is_finite(self.fit_of(s).get("step")) for s in cols):
            row = ["Step at Tm (unfolded − native)"]
            for s in cols:
                f = self.fit_of(s)
                tag = (" (constrained ≥ 0)" if f.get("dir") == "up" else " (constrained ≤ 0)") if f.get("dir") else ""
                row.append(fmt_num(f.get("step"), 3) + tag)
            rows.append(row)
        rows.append(["R²", *[js_to_fixed(self.fit_of(s)["r2"], 4) for s in cols]])
        rows.append(["Sy.x", *[fmt_num(self.fit_of(s)["syx"], 3) for s in cols]])
        rows.append(["N", *[str(self.fit_of(s)["n"]) for s in cols]])
        return rows

    def summary_text(self):
        parts = []
        for s in self.visible:
            if not self.S.get("fit"):
                b = bands(s)
                parts.append(f"{s['name']}: Rpn = {js_to_fixed(b['rpn'], 3)}" if b and math.isfinite(b["rpn"])
                             else s["name"])
                continue
            tm = self.tm(s)
            parts.append(f"{s['name']}: Tm = {fmt_pm(tm['v'], tm['se'])} °C" if tm else s["name"])
        kind = {"melt": "CD melting curve fitted", "spec": "CD spectrum plotted",
                "uv": "UV melting curve fitted"}.get(self.S["mode"], "Graph made")
        return f"{kind} with CD Fit. " + "; ".join(parts)

    def data_table_text(self):
        """Plain copy of the plotted data for the picture's alt text, semicolon-separated as in the add-in."""
        S = self.S
        p = parse_data(S.get("dataText", ""))
        mult = js_parse_float(S.get("yMult"))
        mult = mult if math.isfinite(mult) else 1
        text = S.get("dataText", "")
        comma = bool(re.search("[0-9],[0-9]", text)) and not re.search(r"[0-9]\.[0-9]", text)

        def num(v):
            s = js_str(float(js_to_precision(v, 10)))
            return s.replace(".", ",", 1) if comma else s

        ser = S["series"]
        cols = [j for j in range(len(p["names"])) if not (j < len(ser) and ser[j]) or ser[j].get("visible")]
        head = [p["xName"] or "X"] + [((ser[j].get("name") if j < len(ser) and ser[j] else "") or p["names"][j])
                                      for j in cols]
        cell = lambda s: str(s).replace(";", ",")
        rows = [";".join([num(r[0])] + [num(r[j + 1] * mult) if math.isfinite(r[j + 1]) else "" for j in cols])
                for r in p["rows"]]
        note = f", Y values multiplied by {js_str(mult)}" if mult != 1 else ""
        return (f"DATA (columns separated by ;{note}). Copy the lines below into Excel, then "
                "Data > Text to Columns > Delimited > Semicolon.\n" + "\n".join([";".join(map(cell, head)), *rows]))

    def alt_text(self, state_json):
        return (self.summary_text() + "\n\n" + self.data_table_text()
                + "\n\n---- CD Fit settings (used by the add-in) ----\n" + TAG + state_json)


# ============================ Example data ============================
def example_data(mode="melt"):
    """The add-in's example data sets (same generator and seed)."""
    seed = 7

    def rnd():
        nonlocal seed
        seed = (seed * 16807) % 2147483647
        return seed / 2147483647

    def gauss():
        a = math.sqrt(-2 * math.log(rnd() + 1e-12))
        return a * math.cos(2 * math.pi * rnd())

    g = lambda x, c, w: math.exp(-(((x - c) / w) ** 2))
    model = compile_model(PRESETS["cmp"]["text"])
    fn = lambda x, p: float(model.fn(np.array([x]), p)[0])
    if mode == "spec":   # triple helix at 4 °C (positive band ~225 nm) vs unfolded at 80 °C
        out = ["λ (nm)\tCMP-1 (4 °C)\tCMP-1 (80 °C)"]
        x = 190.0
        while x <= 260 + 1e-9:
            folded = 2.6 * g(x, 225, 7.5) - 38 * g(x, 197.5, 6.5) - 1.2 * g(x, 212, 10) + gauss() * 0.08
            unfolded = -1.0 * g(x, 228, 9) - 22 * g(x, 196, 6.5) - 1.5 * g(x, 215, 10) + gauss() * 0.08
            out.append(f"{js_to_fixed(x, 1)}\t{js_to_fixed(folded, 3)}\t{js_to_fixed(unfolded, 3)}")
            x += 0.5
        return "\n".join(out)
    if mode == "uv":     # hyperchromic transition: absorbance rises on unfolding
        out = ["T (°C)\tCMP-1\tCMP-2"]
        x = 10.0
        while x <= 80 + 1e-9:
            y1 = fn(x, [42.5, 0.6836, 0.0008, 0.656, 0.0005]) + gauss() * 0.002
            y2 = fn(x, [33.0, 0.5936, 0.0008, 0.576, 0.0005]) + gauss() * 0.002
            out.append(f"{js_to_fixed(x, 1)}\t{js_to_fixed(y1, 4)}\t{js_to_fixed(y2, 4)}")
            x += 1
        return "\n".join(out)
    lines = ["T (°C)\tCMP-1\tCMP-2"]
    x = 10.0
    while x <= 60 + 1e-9:
        y1 = fn(x, [42.5, 38.75, -0.11, 16.0, -0.005]) + gauss() * 0.07
        y2 = fn(x, [33.0, 36.5, -0.105, 15.2, -0.006]) + gauss() * 0.07
        lines.append(f"{js_to_fixed(x, 1)}\t{js_to_fixed(y1, 3)}\t{js_to_fixed(y2, 3)}")
        x += 1
    return "\n".join(lines)
