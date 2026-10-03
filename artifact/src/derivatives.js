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

  // The melting mode that is not on screen keeps its state in MODE_STORE; fit it with the add-in's own
  // functions, then put the live page state back. Results are kept per state, so typing refits only once.
  const fitted = new Map();
  const keyOf = (st) => JSON.stringify([st.mode, st.dataText, st.eqText, st.params, st.xFrom, st.xTo, st.yMult,
    st.stepDir, st.fit, (st.series || []).map((c) => c && [c.visible, c.name, c.color])]);
  function fitStored(st) {
    const key = keyOf(st);
    if (fitted.has(key)) return fitted.get(key);
    const live = [S, DATA, MODEL, FITS];
    let out = null;
    try {
      S = JSON.parse(JSON.stringify(st));
      buildData();
      MODEL = S.fit ? compileModel(S.eqText) : null;
      runFits();
      out = { st: S, data: DATA, model: MODEL, fits: FITS };
    } catch (e) {
      out = null;
    } finally {
      [S, DATA, MODEL, FITS] = live;
    }
    fitted.set(key, out);
    if (fitted.size > 4) fitted.delete(fitted.keys().next().value);
    return out;
  }

  function sources() {
    const out = [], freshPage = isExample(S);
    for (const mode of MELT_MODES) {
      let src = null;
      if (S.mode === mode) {
        if (S.fit && MODEL) src = { st: S, data: DATA, model: MODEL, fits: FITS, example: freshPage };
      } else {
        // a page still on its example data shows both examples; otherwise only data the viewer gave
        const st = MODE_STORE[mode] || (freshPage ? modeDefaults(mode) : null);
        const r = st && st.fit ? fitStored(st) : null;
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

  // Three panels on one temperature axis, in the add-in's graph style
  function draw(curves) {
    const F = S.fmt, fs = +F.fontSize || 16, fam = F.fontFamily || "Arial", tfs = fs * 1.06;
    const pw = +F.plotW || 430, ph = +F.plotH || 290, tick = fs * 0.45, minorTick = tick * 0.55;
    const aw = +F.axisW || 1.25, lw = +F.lineW > 0 ? +F.lineW : 2;
    const hs = [Math.round(ph * 0.72), Math.round(ph * 0.6), Math.round(ph * 0.6)], gap = Math.ceil(fs * 1.25);
    const xa = makeAxis(curves.flatMap((c) => [c.xs[0], c.xs[c.xs.length - 1]]), "", "", "", F.xMinor, false, false);
    // alpha on a fixed -0.25..1.25 scale while the points fit it; dα/dT from 0 (rounding gives it tiny negatives)
    const av = curves.flatMap((c) => c.a.concat(c.pts.map((q) => q[1]))), d1v = curves.flatMap((c) => c.d1);
    const aFixed = Math.min(...av) >= -0.25 && Math.max(...av) <= 1.25;
    const ya = [
      aFixed ? makeAxis(av, "-0.25", "1.25", "0.25", 1, false, true) : makeAxis(av, "", "", "", 1, false, true),
      makeAxis(d1v, Math.min(...d1v) > -1e-6 * Math.max(...d1v) ? "0" : "", "", "", 1, false, true),
      makeAxis(curves.flatMap((c) => c.d2), "", "", "", 1, false, true),
    ];
    const labW = Math.max(...ya.map((ax) => Math.max(...ax.ticks.map((v) => markupWidth(ax.label(v), fs, fam)))));
    const ml = Math.ceil(tick + 5 + labW + 10 + tfs * 1.05 + 8), mt = Math.ceil(fs * 0.7);
    const mr = Math.ceil(Math.max(12, markupWidth(xa.label(xa.ticks[xa.ticks.length - 1]), fs, fam) / 2 + 6));
    const mb = Math.ceil(tick + 5 + fs + 8 + tfs * 1.1 + 8);
    const tops = [mt, mt + hs[0] + gap, mt + hs[0] + gap + hs[1] + gap];
    const W = ml + pw + mr, H = tops[2] + hs[2] + mb;
    const X = (v) => ml + xa.frac(v) * pw, f = (v) => v.toFixed(2);
    const dash = (c) => (c.mode === "uv" ? ' stroke-dasharray="7,4"' : "");
    let s = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="${esc(fam)}" font-size="${fs}">`;
    s += `<rect width="${W}" height="${H}" fill="#ffffff"/><defs>`;
    tops.forEach((t, k) => { s += `<clipPath id="dclip${k}"><rect x="${ml}" y="${t - 2}" width="${pw + 2}" height="${hs[k] + 4}"/></clipPath>`; });
    s += "</defs>";
    tops.forEach((top, k) => {
      const ax = ya[k], h = hs[k], by = top + h, Y = (v) => top + h - ax.frac(v) * h;
      if (k > 0 && ax.min < 0 && ax.max > 0)
        s += `<line x1="${ml}" y1="${f(Y(0))}" x2="${f(ml + pw)}" y2="${f(Y(0))}" stroke="#000000" stroke-width="${f(aw * 0.6)}" stroke-dasharray="3,3" opacity="0.55"/>`;
      if (k > 0) curves.forEach((c) => {
        if (!c.peak.edge && c.peak.x >= xa.min && c.peak.x <= xa.max)
          s += `<line x1="${f(X(c.peak.x))}" y1="${top}" x2="${f(X(c.peak.x))}" y2="${f(by)}" stroke="${c.color}" stroke-width="1" stroke-dasharray="2,3" opacity="0.85"/>`;
      });
      s += `<g clip-path="url(#dclip${k})" fill="none" stroke-width="${lw}" stroke-linejoin="round">`;
      curves.forEach((c) => {
        const ys = [c.a, c.d1, c.d2][k];
        let d = "";
        c.xs.forEach((x, i) => {
          const py = Y(ys[i]);
          if (isFinite(py)) d += (d ? "L" : "M") + f(X(x)) + "," + f(Math.max(-1e4, Math.min(1e4, py)));
        });
        s += `<path d="${d}" stroke="${c.color}"${dash(c)}/>`;
      });
      s += "</g>";
      if (k === 0) curves.forEach((c) => {
        for (const [x, y] of c.pts) {
          if (x < xa.min || x > xa.max || y < ax.min || y > ax.max) continue;
          s += `<circle cx="${f(X(x))}" cy="${f(Y(y))}" r="2.6" fill="${c.mode === "uv" ? "#ffffff" : c.color}" stroke="${c.color}" stroke-width="${c.mode === "uv" ? 1.2 : 0.5}" opacity="0.75"/>`;
        }
      });
      s += `<g stroke="#000000" stroke-width="${aw}" fill="none" stroke-linecap="square">`;
      s += `<line x1="${ml}" y1="${f(by)}" x2="${f(ml + pw)}" y2="${f(by)}"/><line x1="${ml}" y1="${top}" x2="${ml}" y2="${f(by)}"/>`;
      xa.ticks.forEach((v) => { s += `<line x1="${f(X(v))}" y1="${f(by)}" x2="${f(X(v))}" y2="${f(by + tick)}"/>`; });
      xa.minor.forEach((v) => { s += `<line x1="${f(X(v))}" y1="${f(by)}" x2="${f(X(v))}" y2="${f(by + minorTick)}"/>`; });
      ax.ticks.forEach((v) => { s += `<line x1="${ml}" y1="${f(Y(v))}" x2="${f(ml - tick)}" y2="${f(Y(v))}"/>`; });
      ax.minor.forEach((v) => { s += `<line x1="${ml}" y1="${f(Y(v))}" x2="${f(ml - minorTick)}" y2="${f(Y(v))}"/>`; });
      s += `</g><g fill="#000000">`;
      if (k === 2) xa.ticks.forEach((v) => { s += `<text x="${f(X(v))}" y="${f(by + tick + 5 + fs * 0.78)}" text-anchor="middle">${markupTspans(xa.label(v), fs)}</text>`; });
      ax.ticks.forEach((v) => { s += `<text x="${f(ml - tick - 5)}" y="${f(Y(v) + fs * 0.36)}" text-anchor="end">${markupTspans(ax.label(v), fs)}</text>`; });
      const tx = ml - tick - 5 - labW - 10 - tfs * 0.25;
      s += `<text transform="translate(${f(tx)},${f(top + h / 2)}) rotate(-90)" x="0" y="0" text-anchor="middle" font-size="${f(tfs)}">${markupTspans(TITLES[k], tfs)}</text>`;
      if (k === 2) s += `<text x="${f(ml + pw / 2)}" y="${f(by + tick + 5 + fs + 8 + tfs * 0.8)}" text-anchor="middle" font-size="${f(tfs)}">${markupTspans("*T* (°C)", tfs)}</text>`;
      s += "</g>";
    });
    const lfs = fs * 0.8, lh = lfs * 1.45, sym = lfs * 2.2, lx = ml + 14, ly = tops[0] + 8;
    s += `<g font-size="${f(lfs)}">`;
    curves.forEach((c, k) => {
      const cy = ly + lh * k + lh / 2;
      s += `<line x1="${f(lx)}" y1="${f(cy)}" x2="${f(lx + sym * 0.8)}" y2="${f(cy)}" stroke="${c.color}" stroke-width="${lw}"${dash(c)}/>`;
      s += `<circle cx="${f(lx + sym * 0.4)}" cy="${f(cy)}" r="3" fill="${c.mode === "uv" ? "#ffffff" : c.color}" stroke="${c.color}" stroke-width="1.2"/>`;
      s += `<text x="${f(lx + sym)}" y="${f(cy + lfs * 0.36)}">${markupTspans(c.name.replace(/[*^_{}\\]/g, "") + " · " + c.tag, lfs)}</text>`;
    });
    s += "</g></svg>";
    return { svg: s, width: W, height: H };
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
