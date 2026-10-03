"""CD Fit graphs: the add-in's renderSVG layout (Prism style) drawn with matplotlib.

Sizes are worked out in the add-in's pixel units (font 16, plot 430 x 290, ...) and the figure is scaled
so that its width is the export width (12 cm by default), so a graph here matches one inserted by the add-in.
Text markup in titles and legends: *italic*, ^{superscript}, _{subscript}.
"""
from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
from matplotlib import ft2font  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties, findfont, get_font  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402

import cdfit_engine as E  # noqa: E402
from cdfit_engine import fmt_num, fmt_tick, js_number, js_parse_float, js_round, js_to_fixed  # noqa: E402

DASHES = {"solid": None, "dash": (7, 4), "dot": (1.5, 3.5), "dashdot": (7, 3, 1.5, 3)}
_FALLBACK = {"sans": ["Arial", "Liberation Sans", "Arimo", "Helvetica", "DejaVu Sans"],
             "serif": ["Times New Roman", "Liberation Serif", "Tinos", "DejaVu Serif"],
             "calibri": ["Calibri", "Carlito", "Arial", "Liberation Sans", "DejaVu Sans"]}
_family_cache = {}


def resolve_family(fam):
    """The first installed font of fam and its metric-compatible stand-ins (Arial → Liberation Sans on Linux)."""
    if fam not in _family_cache:
        low = (fam or "").lower()
        chain = [fam] + _FALLBACK["serif" if "times" in low else "calibri" if "calibri" in low else "sans"]
        _family_cache[fam] = "DejaVu Sans"
        for name in chain:
            try:
                findfont(FontProperties(family=name), fallback_to_default=False)
                _family_cache[fam] = name
                break
            except ValueError:
                continue
    return _family_cache[fam]


def _or(v, default):
    """JavaScript's `+v || default`."""
    v = js_number(v)
    return v if v and not math.isnan(v) else default


# ============================ Text markup ============================
def markup_segments(s):
    segs, buf, italic, i, stack = [], "", False, 0, []

    def push():
        nonlocal buf
        if buf:
            segs.append((buf, italic, stack[-1] if stack else 0))
            buf = ""

    s = str(s)
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            buf += s[i + 1]
            i += 2
            continue
        if c == "*":
            push()
            italic = not italic
            i += 1
            continue
        if c in "^_" and i + 1 < len(s) and s[i + 1] == "{":
            push()
            stack.append(1 if c == "^" else -1)
            i += 2
            continue
        if c == "}" and stack:
            push()
            stack.pop()
            i += 1
            continue
        buf += c
        i += 1
    push()
    return segs


_NO_HINTING = ft2font.LoadFlags.NO_HINTING if hasattr(ft2font, "LoadFlags") else ft2font.LOAD_NO_HINTING
_KERN = ft2font.Kerning.DEFAULT if hasattr(ft2font, "Kerning") else ft2font.KERNING_DEFAULT


class _Fonts:
    """Text in the add-in's pixel units: a 16 px font is measured as 16 pt at 72 dpi. Widths are pen advances
    (with kerning), like the browser's measureText that the add-in uses for its layout."""

    def __init__(self, family):
        self.family = resolve_family(family)
        self._files = {}

    def prop(self, size, italic=False):
        return FontProperties(family=self.family, style="italic" if italic else "normal", size=size)

    def advance(self, text, size, italic=False):
        if italic not in self._files:
            self._files[italic] = findfont(self.prop(10, italic))
        font = get_font(self._files[italic])
        font.set_size(size, 72)
        x, prev = 0.0, None
        for ch in text:
            gi = font.get_char_index(ord(ch))
            if prev is not None:
                x += font.get_kerning(prev, gi, _KERN) / 64
            x += font.load_glyph(gi, flags=_NO_HINTING).linearHoriAdvance / 65536
            prev = gi
        return x

    def width(self, markup, fs):
        return sum(self.advance(t, fs * 0.7 if sc else fs, it) for t, it, sc in markup_segments(markup))


# ============================ Axes ============================
def nice_step(raw):
    if not (raw > 0):
        return 1
    e = math.pow(10, math.floor(math.log10(raw)))
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= raw * (1 - 1e-9):
            return m * e
    return 10 * e


def auto_axis(lo, hi, user_min, user_max, user_step, pad=True):
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = 0.0, 1.0
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    u_min, u_max, u_step = js_parse_float(user_min), js_parse_float(user_max), js_parse_float(user_step)
    if math.isfinite(u_min):
        lo = u_min
    elif 0 <= lo <= hi * 0.5:
        lo = 0.0
    if math.isfinite(u_max):
        hi = u_max
    elif lo * 0.5 <= hi <= 0:
        hi = 0.0
    if hi <= lo:
        hi = lo + 1
    step = u_step if u_step > 0 else nice_step((hi - lo) / 4)
    mn = u_min if math.isfinite(u_min) else math.floor(lo / step + 1e-9) * step
    mx = u_max if math.isfinite(u_max) else math.ceil(hi / step - 1e-9) * step
    if pad and not math.isfinite(u_max) and mx - hi < 0.04 * (mx - mn):
        mx += step
    if pad and not math.isfinite(u_min) and mn != 0 and lo - mn < 0.04 * (mx - mn):
        mn -= step
    return mn, mx, step


class Axis:
    """Ticks and a value → fraction mapping; log axes put major ticks on decades."""

    def __init__(self, vals, user_min, user_max, user_step, minor_n, log, pad=True):
        minor_n = max(0, js_round(_or(minor_n, 0)))
        self.log = log
        self.minor = []
        if not log:
            self.min, self.max, self.step = auto_axis(min(vals) if vals else math.inf, max(vals) if vals else -math.inf,
                                                      user_min, user_max, user_step, pad)
            self.ticks = []
            n = js_round((self.max - self.min) / self.step)
            if n > 200 or n < 0:
                self.ticks = [self.min, self.max]
            else:
                i = 0
                while i <= n + 1e-9:
                    self.ticks.append(self.min + i * self.step)
                    i += 1
                if self.ticks and self.ticks[-1] < self.max - self.step * 1e-6:
                    self.ticks.append(self.max)
            for i in range(len(self.ticks) - 1):
                for k in range(1, minor_n + 1):
                    self.minor.append(self.ticks[i] + (self.ticks[i + 1] - self.ticks[i]) * k / (minor_n + 1))
            return
        pos = [v for v in vals if v > 0]
        u_min, u_max = js_parse_float(user_min), js_parse_float(user_max)
        mn = u_min if u_min > 0 else (math.pow(10, math.floor(math.log10(min(pos)) + 1e-9)) if pos else 1.0)
        mx = u_max if u_max > mn else (math.pow(10, math.ceil(math.log10(max(pos)) - 1e-9)) if pos else 10.0)
        if mx <= mn:
            mx = mn * 10
        self.min, self.max, self.step = mn, mx, 1
        self.l0, self.l1 = math.log10(mn), math.log10(mx)
        self.ticks = [math.pow(10, k) for k in range(math.ceil(self.l0 - 1e-9), math.floor(self.l1 + 1e-9) + 1)]
        if len(self.ticks) < 2:
            self.ticks = [mn, mx]
        if minor_n > 0:
            for k in range(math.floor(self.l0) - 1, math.ceil(self.l1) + 1):
                for m in range(2, 10):
                    v = m * math.pow(10, k)
                    if mn * (1 + 1e-9) < v < mx * (1 - 1e-9):
                        self.minor.append(v)

    def frac(self, v):
        if self.log:
            return (math.log10(v) - self.l0) / (self.l1 - self.l0) if v > 0 else math.nan
        return E.js_div(v - self.min, self.max - self.min)

    def label(self, v):
        if not self.log:
            return fmt_tick(v, self.step)
        k = js_round(math.log10(v))
        if abs(v - math.pow(10, k)) < v * 1e-9 and (k < -3 or k > 4):
            return f"10^{{{k}}}".replace("-", "−", 1)
        return fmt_num(v, 4)


# ============================ Styles ============================
def style_of(S, j):
    c = (S["series"][j] if j < len(S["series"]) else None) or {}
    size = js_parse_float(c.get("size"))
    return {
        "color": c.get("color") or E.COLORS[j % len(E.COLORS)],
        "shape": c.get("shape") or E.SHAPES[j % len(E.SHAPES)],
        "hollow": c.get("fill") == "hollow" if c.get("fill") else bool(S["fmt"].get("hollow")),
        "size": size if math.isfinite(size) else js_number(S["fmt"].get("markerSize")),
        "line": c.get("line") or "solid",
    }


# ============================ Drawing in pixel units ============================
class _Canvas:
    def __init__(self, W, H, width_cm, fonts):
        self.W, self.H, self.fonts = W, H, fonts
        win = width_cm / 2.54
        self.pt = win * 72 / W                     # points per add-in pixel
        self.fig = Figure(figsize=(win, win * H / W))
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, W)
        self.ax.set_ylim(H, 0)
        self.ax.set_axis_off()
        self.z = 0
        self.ax.add_patch(Rectangle((0, 0), W, H, facecolor="#ffffff", edgecolor="none", zorder=self._z()))

    def _z(self):
        self.z += 1
        return self.z

    def _dashes(self, pattern, width):
        lw = width * self.pt
        if not pattern or lw <= 0:
            return "-"
        scale = lw if matplotlib.rcParams["lines.scale_dashes"] else 1.0
        return (0, tuple(d * self.pt / scale for d in pattern))

    def line(self, xs, ys, color, width, dash=None, cap="butt", join="miter", alpha=None, clip=None):
        if width <= 0:
            return
        ln = Line2D(xs, ys, color=color, linewidth=width * self.pt, linestyle=self._dashes(dash, width),
                    solid_capstyle=cap, dash_capstyle=cap, solid_joinstyle=join, dash_joinstyle=join,
                    alpha=alpha, zorder=self._z())
        self.ax.add_line(ln)
        if clip is not None:
            ln.set_clip_path(clip)

    def marker(self, shape, x, y, r, color, hollow, sw, alpha=None):
        if shape == "none":
            return
        fill = "#ffffff" if hollow else color
        lw = (sw if hollow else 0.5) * self.pt
        kw = dict(facecolor=fill, edgecolor=color, linewidth=lw, alpha=alpha, zorder=self._z())
        if shape in ("cross", "plus"):
            w = max(1.2, r / 2.5)
            if shape == "cross":
                a = r * 0.95
                self.line([x - a, x + a], [y - a, y + a], color, w, alpha=alpha)
                self.line([x - a, x + a], [y + a, y - a], color, w, alpha=alpha)
            else:
                a = r * 1.1
                self.line([x - a, x + a], [y, y], color, w, alpha=alpha)
                self.line([x, x], [y - a, y + a], color, w, alpha=alpha)
            return
        if shape == "square":
            a = r * 0.9
            p = Rectangle((x - a, y - a), 2 * a, 2 * a, **kw)
        elif shape == "triangle":
            a = r * 1.2
            p = Polygon([(x, y - a), (x + a * 0.95, y + a * 0.65), (x - a * 0.95, y + a * 0.65)], closed=True, **kw)
        elif shape == "tridown":
            a = r * 1.2
            p = Polygon([(x, y + a), (x + a * 0.95, y - a * 0.65), (x - a * 0.95, y - a * 0.65)], closed=True, **kw)
        elif shape == "diamond":
            a = r * 1.25
            p = Polygon([(x, y - a), (x + a, y), (x, y + a), (x - a, y)], closed=True, **kw)
        else:
            p = Circle((x, y), r, **kw)
        self.ax.add_patch(p)

    def text(self, x, y, markup, fs, anchor="start", rotate=False):
        """The add-in's markupTspans: segments in a row, sub/superscripts at 0.7 size shifted from the baseline."""
        segs = markup_segments(markup)
        widths = [self.fonts.advance(t, fs * 0.7 if sc else fs, it) for t, it, sc in segs]
        pos = {"start": 0.0, "middle": -sum(widths) / 2, "end": -sum(widths)}[anchor]
        for (t, it, sc), w in zip(segs, widths):
            shift = -0.38 * fs if sc == 1 else 0.22 * fs if sc == -1 else 0.0
            px, py = (x + shift, y - pos) if rotate else (x + pos, y + shift)
            self.ax.text(px, py, t, fontproperties=self.fonts.prop((fs * 0.7 if sc else fs) * self.pt, it),
                         ha="left", va="baseline", rotation=90 if rotate else 0, rotation_mode="anchor",
                         color="#000000", parse_math=False, zorder=self._z())
            pos += w

    def save(self, path, dpi):
        with matplotlib.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
            self.fig.savefig(path, dpi=dpi, facecolor="#ffffff")


def render(session, paths, dpi=None):
    """Draw the session's graph to each path (.png, .svg or .pdf). Returns (width px, height px, width cm)."""
    S, fits, model = session.S, session.fits, session.model
    F = S["fmt"]
    fs = _or(F.get("fontSize"), 16)
    fonts = _Fonts(F.get("fontFamily") or "Arial")
    tfs = fs * 1.06
    pw, ph = _or(F.get("plotW"), 430), _or(F.get("plotH"), 290)
    tick = fs * 0.45
    minor_tick = tick * 0.55
    aw = _or(F.get("axisW"), 1.25)
    line_w = js_number(F.get("lineW"))
    vis = session.visible
    all_x = [v for s in vis for v in s["xs"] + s["xsEx"]]
    all_y = [v for s in vis for v in s["ys"] + s["ysEx"]]
    pad = not F.get("connect")   # spectra (connected lines) get tight axes
    xa = Axis(all_x, F.get("xMin"), F.get("xMax"), F.get("xStep"), F.get("xMinor"), F.get("xScale") == "log", pad)
    ya = Axis(all_y, F.get("yMin"), F.get("yMax"), F.get("yStep"), F.get("yMinor"), F.get("yScale") == "log", pad)
    xt, yt = xa.ticks, ya.ticks
    y_lab_w = max(fonts.width(ya.label(v), fs) for v in yt)
    x_last_w = fonts.width(xa.label(xt[-1]), fs)
    ml = math.ceil(tick + 5 + y_lab_w + 10 + tfs * 1.05 + 8)
    mt = math.ceil(fs * 0.7)
    mr = math.ceil(max(12, x_last_w / 2 + 6))
    mb = math.ceil(tick + 5 + fs + 8 + tfs * 1.1 + 8)
    W, H = ml + pw + mr, mt + ph + mb
    X = lambda v: ml + xa.frac(v) * pw
    Y = lambda v: mt + ph - ya.frac(v) * ph
    width_cm = _or(F.get("exportCm"), 12)
    c = _Canvas(W, H, width_cm, fonts)
    clip = Rectangle((ml, mt - 2), pw + 2, ph + 4, transform=c.ax.transData)

    tm_of = lambda ser: E.param_value(fits[ser["idx"]] if ser["idx"] < len(fits) else None, model, "Tm")
    fit_of = lambda ser: fits[ser["idx"]] if ser["idx"] < len(fits) else None

    # zero line
    if F.get("zeroLine") and not ya.log and ya.min < 0 < ya.max:
        c.line([ml, ml + pw], [Y(0), Y(0)], "#000000", aw * 0.7)
    # Tm lines
    if F.get("tmLine") and S.get("fit"):
        for ser in vis:
            tm = tm_of(ser)
            if tm and math.isfinite(tm["v"]) and xa.min <= tm["v"] <= xa.max:
                c.line([X(tm["v"]), X(tm["v"])], [mt, mt + ph], style_of(S, ser["idx"])["color"], 1, dash=(2, 3),
                       alpha=0.8)
    # fitted curves
    if F.get("showCurve") and model:
        for ser in vis:
            fit, st = fit_of(ser), style_of(S, ser["idx"])
            if not fit or fit.get("error") or not (line_w > 0) or st["line"] == "none":
                continue
            x0, x1 = min(ser["xs"]), max(ser["xs"])
            if F.get("curveAxis"):
                x0, x1 = xa.min, xa.max
            logx = xa.log and x0 > 0
            if logx:
                xsc = [math.pow(10, math.log10(x0) + (math.log10(x1) - math.log10(x0)) * i / 400) for i in range(401)]
            else:
                xsc = [x0 + (x1 - x0) * i / 400 for i in range(401)]
            ysc = model.fn(xsc, fit["p"])
            px, py = [], []
            for x, y in zip(xsc, ysc):
                yy = Y(float(y)) if math.isfinite(y) else math.nan
                if not math.isfinite(yy):
                    px.append(math.nan)
                    py.append(math.nan)
                    continue
                px.append(X(x))
                py.append(max(-1e4, min(1e4, yy)))
            c.line(px, py, st["color"], line_w, dash=DASHES.get(st["line"]),
                   cap="round" if st["line"] == "dot" else "butt", join="round", clip=clip)
    # lines through the data (spectra)
    if F.get("connect") and line_w > 0:
        for ser in vis:
            st = style_of(S, ser["idx"])
            if st["line"] == "none":
                continue
            order = sorted(range(len(ser["xs"])), key=lambda i: ser["xs"][i])
            px, py = [], []
            for i in order:
                a, b = X(ser["xs"][i]), Y(ser["ys"][i])
                if not (math.isfinite(a) and math.isfinite(b)):
                    px.append(math.nan)
                    py.append(math.nan)
                    continue
                px.append(a)
                py.append(b)
            c.line(px, py, st["color"], line_w, dash=DASHES.get(st["line"]),
                   cap="round" if st["line"] == "dot" else "butt", join="round", clip=clip)
    # points (excluded ones faded)
    if F.get("showPoints"):
        for ser in vis:
            st = style_of(S, ser["idx"])
            r = st["size"]
            if not (r > 0) or st["shape"] == "none":
                continue
            for xs, ys, alpha in ((ser["xsEx"], ser["ysEx"], 0.3), (ser["xs"], ser["ys"], None)):
                for x, y in zip(xs, ys):
                    if x < xa.min or x > xa.max or y < ya.min or y > ya.max:
                        continue
                    c.marker(st["shape"], X(x), Y(y), r, st["color"], st["hollow"], max(1, r / 4), alpha)

    # axes
    by = mt + ph
    c.line([ml, ml + pw], [by, by], "#000000", aw, cap="projecting")
    c.line([ml, ml], [mt, by], "#000000", aw, cap="projecting")
    for v in xt:
        c.line([X(v), X(v)], [by, by + tick], "#000000", aw, cap="projecting")
    for v in xa.minor:
        c.line([X(v), X(v)], [by, by + minor_tick], "#000000", aw, cap="projecting")
    for v in yt:
        c.line([ml, ml - tick], [Y(v), Y(v)], "#000000", aw, cap="projecting")
    for v in ya.minor:
        c.line([ml, ml - minor_tick], [Y(v), Y(v)], "#000000", aw, cap="projecting")
    for v in xt:
        c.text(X(v), by + tick + 5 + fs * 0.78, xa.label(v), fs, anchor="middle")
    for v in yt:
        c.text(ml - tick - 5, Y(v) + fs * 0.36, ya.label(v), fs, anchor="end")
    # titles
    c.text(ml + pw / 2, by + tick + 5 + fs + 8 + tfs * 0.8, F.get("xTitle") or "", tfs, anchor="middle")
    c.text(ml - tick - 5 - y_lab_w - 10 - tfs * 0.25, mt + ph / 2, F.get("yTitle") or "", tfs, anchor="middle",
           rotate=True)

    # legend
    if F.get("legend") != "off" and vis:
        lfs = fs * 0.85
        lh = lfs * 1.45
        r = min(_or(F.get("markerSize"), 5), lfs * 0.4)
        items = []
        for ser in vis:
            label = ser["name"]
            tm = tm_of(ser)
            if F.get("legendTm") and tm and math.isfinite(tm["v"]):
                label += f" (*T*_{{m}} = {js_to_fixed(tm['v'], 1)} °C)"
            items.append((ser, label, fonts.width(label, lfs)))
        sym = lfs * 2.0
        lw = sym + max(w for _, _, w in items)
        pad_l = 8
        legend = F.get("legend") or "tr"
        lx = ml + pad_l + 6 if legend.endswith("l") else ml + pw - pad_l - lw
        ly = mt + pad_l if legend.startswith("t") else mt + ph - pad_l - lh * len(items)
        for k, (ser, label, _) in enumerate(items):
            cy = ly + lh * k + lh / 2
            st = style_of(S, ser["idx"])
            rr = min(st["size"] or r, lfs * 0.4) if not math.isnan(st["size"]) else min(r, lfs * 0.4)
            fit = fit_of(ser)
            if ((F.get("showCurve") and fit and not fit.get("error")) or F.get("connect")) and line_w > 0 \
                    and st["line"] != "none":
                c.line([lx, lx + sym * 0.8], [cy, cy], st["color"], line_w, dash=DASHES.get(st["line"]))
            if F.get("showPoints") and rr > 0:
                c.marker(st["shape"], lx + sym * 0.4, cy, rr, st["color"], st["hollow"], max(1, rr / 4))
            c.text(lx + sym, cy + lfs * 0.36, label, lfs)

    fmt = F.get("exportFmt") or "png300"
    for path in paths:
        c.save(path, dpi or (600 if fmt == "png600" else 300))
    return W, H, width_cm
