"use strict";
/* 1st and 2nd derivatives of the CD and UV melting fits in one figure, in its own section below the app.
   Each fit is expressed as the fraction unfolded, alpha = (Y - native baseline) / (unfolded - native baseline),
   so CD (falls on unfolding) and UV (rises) share the axes. The fits come from the add-in's own functions. */
const cdfitDerivatives = (function () {
  const MELT_MODES = ["melt", "uv"];
  const TAG = { melt: "CD", uv: "UV" };
  const TITLES = ["*α* (fraction unfolded)", "d*α*/d*T* (°C^{−1})", "d^{2}*α*/d*T*^{2} (°C^{−2})"];
  const box = $("derivSvgBox"), tableBox = $("derivTable"), note = $("derivNote");
  const examples = {};
  const isExample = (st) => {
    if (!(st.mode in examples)) examples[st.mode] = exampleData(st.mode).trim();
    return (st.dataText || "").trim() === examples[st.mode];
  };

  // The melting mode that is not on screen keeps its state in MODE_STORE (fitted by cdfitFitState, page.js)
  function sources() {
    const out = [], freshPage = isExample(S);
    for (const mode of MELT_MODES) {
      let src = null;
      if (S.mode === mode) {
        if (S.fit && MODEL) src = { st: S, data: DATA, model: MODEL, fits: FITS, example: freshPage };
      } else {
        // a page still on its example data shows both examples; otherwise only data the viewer gave
        const st = MODE_STORE[mode] || (freshPage ? modeDefaults(mode) : null);
        const r = st && st.fit ? cdfitFitState(st) : null;
        if (r && r.model) src = { ...r, example: isExample(r.st) };
      }
      if (src) out.push({ mode, ...src });
    }
    return out;
  }

  const argmax = (a) => a.reduce((best, v, i) => (v > a[best] ? i : best), 0);
  function vertex(xs, ys, i) {            // the top of a parabola through the grid points around i
    if (i <= 0 || i >= ys.length - 1) return { x: xs[i], edge: true };
    const y0 = ys[i - 1], y1 = ys[i], y2 = ys[i + 1], den = y0 - 2 * y1 + y2;
    const off = den ? Math.max(-1, Math.min(1, (0.5 * (y0 - y2)) / den)) : 0;
    return { x: xs[i] + off * (xs[1] - xs[0]), edge: false };
  }

  function analyse(src) {
    const { mode, st, data, model, fits } = src;
    const baselines = stepSupported(model), iTm = model.keys.indexOf("tm"), out = [];
    data.series.forEach((ser, j) => {
      const fit = fits[j], cfg = st.series[j];
      if (!fit || fit.error || !cfg || !cfg.visible || ser.xs.length < 3) return;
      const p = fit.p, x0 = Math.min(...ser.xs), x1 = Math.max(...ser.xs);
      const Y = (x) => model.fn(x, p);
      let alpha;
      if (baselines) alpha = (x) => { const v = model.vars(x, p); return (v.y - v.cdn) / (v.cdu - v.cdn); };
      else { const ya = Y(x0), yb = Y(x1); alpha = (x) => (Y(x) - ya) / (yb - ya); }
      const N = 600, h = 0.01, h2 = 0.03, xs = [], a = [], d1 = [], d2 = [], r1 = [];
      for (let i = 0; i <= N; i++) {
        const x = x0 + ((x1 - x0) * i) / N, a0 = alpha(x);
        xs.push(x);
        a.push(a0);
        d1.push((alpha(x + h) - alpha(x - h)) / (2 * h));
        d2.push((alpha(x + h2) - 2 * a0 + alpha(x - h2)) / (h2 * h2));
        r1.push((Y(x + h) - Y(x - h)) / (2 * h));
      }
      if (![a, d1, d2, r1].every((arr) => arr.every(isFinite))) return;
      const ip = argmax(d1), sign = Math.sign(r1[ip]) || 1, rs = r1.map((v) => sign * v), neg = d2.map((v) => -v);
      const pts = ser.xs.map((x, i) => {
        if (!baselines) { const ya = Y(x0), yb = Y(x1); return [x, (ser.ys[i] - ya) / (yb - ya)]; }
        const v = model.vars(x, p);
        return [x, (ser.ys[i] - v.cdn) / (v.cdu - v.cdn)];
      });
      out.push({
        name: ser.name, mode, tag: TAG[mode], color: cfg.color || COLORS[j % COLORS.length], example: src.example,
        xs, a, d1, d2, pts, tm: iTm >= 0 ? p[iTm] : NaN, tmSe: iTm >= 0 ? fit.se[iTm] : NaN,
        peak: vertex(xs, d1, ip), raw: vertex(xs, rs, argmax(rs)), onset: vertex(xs, d2, argmax(d2)), end: vertex(xs, neg, argmax(neg)),
      });
    });
    return out;
  }

  // α always on one scale; a data point beyond it (where the fitted baselines nearly meet) is left out of the figure
  const A_LO = -0.25, A_HI = 1.25, LEGEND_MAX = 8;
  const outside = (c) => c.pts.filter((q) => !(q[1] >= A_LO && q[1] <= A_HI)).length;

  // Three panels on one temperature axis (panels.js draws them in the add-in's graph style)
  function draw(curves) {
    const d1v = curves.flatMap((c) => c.d1);
    const dash = (c) => (c.mode === "uv" ? "7,4" : "");
    const line = (c, ys) => ({ xs: c.xs, ys, color: c.color, dash: dash(c) });
    const peaks = curves.filter((c) => !c.peak.edge).map((c) => ({ x: c.peak.x, color: c.color }));
    return cdfitPanels({
      xVals: curves.flatMap((c) => [c.xs[0], c.xs[c.xs.length - 1]]), xTitle: "*T* (°C)", legendAt: "tl",
      // more than 8 curves would bury the panels under the legend: the table beside the figure has their colours
      legend: curves.length > LEGEND_MAX ? [] : curves.map((c) => ({ label: cdfitMarkupEscape(c.name) + " · " + c.tag, color: c.color, dash: dash(c), hollow: c.mode === "uv" })),
      panels: [
        { title: TITLES[0], height: 0.72, axis: { min: A_LO, max: A_HI, step: 0.25 },
          lines: curves.map((c) => line(c, c.a)),
          points: curves.flatMap((c) => c.pts.map(([x, y]) => ({ x, y, color: c.color, hollow: c.mode === "uv", opacity: 0.75 }))) },
        // dα/dT from 0: rounding gives it tiny negatives
        { title: TITLES[1], height: 0.6, axis: Math.min(...d1v) > -1e-6 * Math.max(...d1v) ? { min: 0 } : null,
          zero: true, vlines: peaks, lines: curves.map((c) => line(c, c.d1)), points: [] },
        { title: TITLES[2], height: 0.6, zero: true, vlines: peaks, lines: curves.map((c) => line(c, c.d2)), points: [] },
      ],
    });
  }

  const t2 = (v) => (isFinite(v) ? v.toFixed(2) : "—");
  const t1 = (v) => (isFinite(v) ? v.toFixed(1) : "—");
  const at = (pt, fmt) => (pt.edge ? "at the edge" : fmt(pt.x));
  function table(curves) {
    let h = `<table class="t"><thead><tr><th>Data set</th><th class="num">T<sub>m</sub>, fit (°C)</th>` +
      `<th class="num">dα/dT peak (°C)</th><th class="num">dY/dT peak (°C)</th><th class="num">d²α/dT² max to min (°C)</th></tr></thead><tbody>`;
    for (const c of curves) {
      const tm = isFinite(c.tmSe) && c.tmSe > 0 ? fmtPM(c.tm, c.tmSe) : t2(c.tm);
      h += `<tr><td><span class="swatch" style="background:${c.color}"></span> ${esc(c.name)} · ${c.tag}</td>` +
        `<td class="num">${tm}</td><td class="num">${at(c.peak, t2)}</td><td class="num">${at(c.raw, t2)}</td>` +
        `<td class="num">${c.onset.edge || c.end.edge ? "—" : t1(c.onset.x) + " to " + t1(c.end.x)}</td></tr>`;
    }
    return h + "</tbody></table>";
  }

  let curves = [], figure = null;
  function update() {
    curves = sources().flatMap(analyse);
    if (!curves.length) {
      figure = null;
      box.innerHTML = "";
      tableBox.innerHTML = "";
      note.textContent = "Fit a CD or a UV melting curve to see its derivatives here.";
      return;
    }
    figure = draw(curves);
    box.innerHTML = figure.svg;
    tableBox.innerHTML = table(curves);
    const has = new Set(curves.map((c) => c.mode));
    const parts = [];
    if (!has.has("uv")) parts.push("Only CD curves so far: fit data under UV melting to compare both here.");
    if (!has.has("melt")) parts.push("Only UV curves so far: fit data under CD melting to compare both here.");
    if (curves.some((c) => c.example)) parts.push("These curves come from the example data.");
    if (curves.length > LEGEND_MAX) parts.push(`With ${curves.length} curves the figure has no legend: the table gives each one's colour.`);
    const off = curves.filter(outside).map((c) => `${c.name} · ${c.tag} (${outside(c)})`);
    if (off.length) parts.push(`Points with α outside −0.25 to 1.25 are not drawn: ${off.join(", ")}. ` +
      "Where the fitted baselines nearly meet, α is not well defined, so check those baselines.");
    note.textContent = parts.join(" ");
  }

  const stem = () => "Derivatives - " + [...new Set(curves.map((c) => c.name))].slice(0, 3).join(", ").replace(/[\\/:*?"<>|]+/g, "");
  $("derivPng").onclick = async () => {
    if (!figure || !cdfitFiles.save) return;
    try { await cdfitFiles.save(stem() + ".png", await cdfitFiles.pngBlob(figure.svg, figure.width, figure.height)); }
    catch (e) { setStatus(e.message, "err"); }
  };
  $("derivSvg").onclick = () => { if (figure && cdfitFiles.save) cdfitFiles.save(stem() + ".svg", figure.svg); };

  CDFIT_AFTER_REFRESH.push(update);
  update();

  return {
    summary() {
      return curves.map((c) => `${c.name} ${c.tag}: Tm (fit) ${t2(c.tm)}, peak of d(alpha)/dT ${at(c.peak, t2)}, ` +
        `peak of dY/dT ${at(c.raw, t2)}, d2(alpha)/dT2 max ${at(c.onset, t1)} and min ${at(c.end, t1)}`).join("\n");
    },
  };
})();
