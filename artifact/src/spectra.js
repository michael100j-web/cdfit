"use strict";
/* All spectra at once (CD spectrum mode): one table row per spectrum, θ at a chosen wavelength and Rpn against
   the temperature read from each spectrum's name, colours by temperature, and θ(λ) against T sent to CD melting. */
const cdfitSpectra = (function () {
  const sec = $("spectra"), box = $("specSvgBox"), fig = $("specFigure"), tableBox = $("specTable"), note = $("specNote");
  const lamInput = $("specLambda"), meltRow = $("specMeltRow"), confirmRow = $("specConfirm");
  const RAMP = ["#1d4e89", "#2a8c8c", "#7fae4a", "#d39b22", "#d0612f", "#9b2226"];
  let view = null;   // the last analysis: rows, groups, lambda, figure

  // a temperature (or another number) in a spectrum's name, and the name without it
  function labelOf(name) {
    let m = /(-?\d+(?:[.,]\d+)?)\s*(?:°\s*C|℃|deg\s*C|C)(?![A-Za-z])/i.exec(name), celsius = !!m;
    if (!m) {
      const all = [...name.matchAll(/-?\d+(?:[.,]\d+)?/g)];
      m = all.length ? all[all.length - 1] : null;
    }
    if (!m) return null;
    const number = m[1] !== undefined ? m[1] : m[0];   // the °C match captures the number; the fallback is the number
    const rest = (name.slice(0, m.index) + name.slice(m.index + m[0].length)).replace(/\(\s*\)|\[\s*\]/g, " ");
    const group = rest.replace(/^[\s_\-–,;:()[\]]+|[\s_\-–,;:()[\]]+$/g, "").trim();
    const value = parseFloat(number.replace(",", "."));
    // a bare number heading a spectrum, as in a table of spectra, is its temperature
    if (!celsius && /^\s*-?\d+(?:[.,]\d+)?\s*$/.test(name) && value >= -30 && value <= 130) celsius = true;
    return { value, celsius, group: group || "Spectra" };
  }

  function valueAt(ser, lam) {
    const idx = ser.xs.map((_, i) => i).sort((a, b) => ser.xs[a] - ser.xs[b]);
    for (let k = 0; k < idx.length - 1; k++) {
      const i = idx[k], j = idx[k + 1];
      if (ser.xs[i] <= lam && lam <= ser.xs[j]) {
        const span = ser.xs[j] - ser.xs[i];
        return span ? ser.ys[i] + ((lam - ser.xs[i]) / span) * (ser.ys[j] - ser.ys[i]) : ser.ys[i];
      }
    }
    return NaN;
  }

  const units = () => { const m = /\(([^()]*)\)\s*$/.exec(S.fmt.yTitle || ""); return m ? " (" + m[1] + ")" : ""; };
  const lambda = () => { const v = parseFloat(String(lamInput.value).replace(",", ".")); return isFinite(v) ? v : 225; };

  function analyse() {
    const lam = lambda(), rows = [];
    DATA.series.forEach((ser, j) => {
      if (!S.series[j] || !S.series[j].visible || !ser.xs.length) return;
      rows.push({ j, name: ser.name, label: labelOf(ser.name), b: bands(ser), at: valueAt(ser, lam) });
    });
    const labelled = rows.filter((r) => r.label && isFinite(r.label.value));
    const celsius = labelled.length && labelled.every((r) => r.label.celsius);
    const groups = new Map();
    for (const r of labelled) {
      if (!groups.has(r.label.group)) groups.set(r.label.group, []);
      groups.get(r.label.group).push(r);
    }
    for (const g of groups.values()) g.sort((a, b) => a.label.value - b.label.value);
    const trend = labelled.length >= 3 && [...groups.values()].some((g) => new Set(g.map((r) => r.label.value)).size >= 2);
    return { lam, rows, groups, celsius, trend, labelled: labelled.length === rows.length };
  }

  function drawTrend(v) {
    const names = [...v.groups.keys()], colorOf = (k) => COLORS[k % COLORS.length];
    const xs = v.rows.filter((r) => r.label).map((r) => r.label.value);
    const series = (key) => names.map((n, k) => {
      const g = v.groups.get(n).filter((r) => isFinite(key(r)));
      return { xs: g.map((r) => r.label.value), ys: g.map(key), color: colorOf(k) };
    });
    const pts = (key) => names.flatMap((n, k) => v.groups.get(n).filter((r) => isFinite(key(r)))
      .map((r) => ({ x: r.label.value, y: key(r), color: colorOf(k), r: 3.4, opacity: 0.95 })));
    // θ panel: the melting fit where it worked, otherwise straight lines between the points
    const fits = v.fitted || [], joined = series((r) => r.at);
    const thetaLines = names.map((n, k) => (fits[k] && fits[k].xs ? { xs: fits[k].xs, ys: fits[k].ys, color: colorOf(k) } : joined[k]));
    const tmLines = fits.map((f, k) => (f && isFinite(f.tm) ? { x: f.tm, color: colorOf(k) } : null)).filter(Boolean);
    const label = (n, k) => cdfitMarkupEscape(n) + (fits[k] && isFinite(fits[k].tm) ? ` (*T*_{m} = ${fits[k].tm.toFixed(1)} °C)` : "");
    return cdfitPanels({
      xVals: xs, xPad: true, xTitle: v.celsius ? "*T* (°C)" : "Number in the spectrum name", legendAt: "tr",
      legend: names.length > 1 || tmLines.length ? names.map((n, k) => ({ label: label(n, k), color: colorOf(k) })) : [],
      panels: [
        { title: `*θ* at ${fmtNum(v.lam, 4)} nm`, height: 0.7, zero: true, lines: thetaLines, points: pts((r) => r.at), vlines: tmLines },
        { title: "R_{pn}", height: 0.55, lines: series((r) => r.b.rpn), points: pts((r) => r.b.rpn) },
      ],
    });
  }

  // θ at the wavelength against temperature, fitted with CD melting's model (the CMP model unless changed there)
  function meltState(v) {
    const st = MODE_STORE.melt ? JSON.parse(JSON.stringify(MODE_STORE.melt)) : modeDefaults("melt");
    st.dataText = meltTable(v);
    st.series = []; st.xFrom = ""; st.xTo = ""; st.fit = true;
    st.fmt = { ...(st.fmt || {}), yTitle: `*θ*_{${fmtNum(v.lam, 4)}}${units()}` };
    return st;
  }
  function fitTrend(v) {
    const st = meltState(v), r = cdfitFitState(st);
    if (!r || !r.model) return null;
    const iTm = r.model.keys.indexOf("tm");
    const fits = [...v.groups.keys()].map((n, k) => {
      const ser = r.data.series[k], fit = r.fits[k];
      if (!ser || !fit) return { name: n, error: "no points to fit" };
      if (fit.error) return { name: n, error: fit.error };
      const x0 = Math.min(...ser.xs), x1 = Math.max(...ser.xs), xs = [], ys = [];
      for (let i = 0; i <= 200; i++) { const x = x0 + ((x1 - x0) * i) / 200; xs.push(x); ys.push(r.model.fn(x, fit.p)); }
      return { name: n, xs, ys, tm: iTm >= 0 ? fit.p[iTm] : NaN, se: iTm >= 0 ? fit.se[iTm] : NaN };
    });
    const preset = Object.keys(PRESETS).find((k) => PRESETS[k].text.trim() === st.eqText.trim());
    fits.model = preset === "cmp" ? "the CMP model (ΔH −500 kJ/mol)" : preset ? PRESETS[preset].label : "the equation set under CD melting";
    return fits;
  }
  function fitText(v) {
    if (!v.fitted) return "";
    const parts = v.fitted.map((f) => (f.error ? `${f.name}: ${f.error}` : isFinite(f.tm) ? `${f.name} Tm = ${isFinite(f.se) && f.se > 0 ? fmtPM(f.tm, f.se) : fmtNum(f.tm, 4)} °C` : f.name + " fitted"));
    return `θ at ${fmtNum(v.lam, 4)} nm against temperature, fitted with ${v.fitted.model}: ${parts.join("; ")}.`;
  }

  function tableRows(v) {
    const head = ["Spectrum", v.celsius ? "T (°C)" : "Number in name", "λ max (nm)", "Value at max", "λ min (nm)",
      "Value at min", "Crossover (nm)", "Rpn", `Value at ${fmtNum(v.lam, 4)} nm`];
    const body = v.rows.map((r) => [r.name, r.label ? fmtNum(r.label.value, 4) : "—", r.b.hasPos ? fmtNum(r.b.xMax, 5) : "—",
      fmtNum(r.b.yMax, 4), fmtNum(r.b.xMin, 5), fmtNum(r.b.yMin, 4), isFinite(r.b.cross) ? r.b.cross.toFixed(1) : "—",
      isFinite(r.b.rpn) ? r.b.rpn.toFixed(3) : "—", fmtNum(r.at, 4)]);
    return [head, ...body];
  }

  function update() {
    if (S.mode !== "spec" || !DATA || !DATA.series.length) { sec.hidden = true; return; }
    sec.hidden = false;
    const der = $("derivatives");
    if (sec.nextElementSibling !== der) der.parentNode.insertBefore(sec, der);   // in spectrum mode this section comes first
    view = analyse();
    view.fitted = view.trend ? fitTrend(view) : null;
    view.figure = view.trend ? drawTrend(view) : null;
    $("specFit").textContent = fitText(view);
    fig.hidden = !view.figure;
    box.innerHTML = view.figure ? view.figure.svg : "";
    sec.classList.toggle("no-figure", !view.figure);
    const rows = tableRows(view);
    tableBox.innerHTML = `<table class="t"><thead><tr>${rows[0].map((h, i) => `<th${i ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
      rows.slice(1).map((r, k) => `<tr><td><span class="swatch" style="background:${styleOf(view.rows[k].j).color}"></span> ${esc(r[0])}</td>` +
        r.slice(1).map((c) => `<td class="num">${esc(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
    const parts = [`${view.rows.length} spectr${view.rows.length === 1 ? "um" : "a"}.`];
    if (!view.trend) parts.push("Name the spectra with their temperature (for example “CMP-1 20 °C”, or files named that way) to see θ and Rpn against temperature.");
    else if (!view.labelled) parts.push("Spectra without a number in their name are left out of the figure.");
    if (view.rows.length > 10) parts.push("With this many spectra, Colour by temperature helps, and the legend can be hidden in the Graph tab.");
    note.textContent = parts.join(" ");
    meltRow.hidden = !view.trend;
    $("specToMelt").innerHTML = `Fit θ<sub>${esc(fmtNum(view.lam, 4))}</sub> against ${view.celsius ? "temperature" : "the name's number"} in CD melting`;
    confirmRow.hidden = true;
  }

  function ramp(t) {
    const n = RAMP.length - 1, i = Math.min(n - 1, Math.floor(t * n)), u = t * n - i;
    const hex = (c) => [1, 3, 5].map((k) => parseInt(c.slice(k, k + 2), 16));
    const a = hex(RAMP[i]), b = hex(RAMP[i + 1]);
    return "#" + a.map((v, k) => Math.round(v + (b[k] - v) * u).toString(16).padStart(2, "0")).join("");
  }
  $("specGradient").onclick = () => {
    if (!view || !view.rows.length) return;
    const order = view.rows.slice().sort((a, b) => (a.label && b.label ? a.label.value - b.label.value : 0) || a.j - b.j);
    order.forEach((r, k) => { S.series[r.j].color = ramp(order.length > 1 ? k / (order.length - 1) : 0); });
    refresh(true);
    setStatus(view.rows.some((r) => r.label) ? "Coloured from blue (lowest temperature) to red (highest)." : "Coloured in column order, blue to red.", "ok");
  };

  $("specCopy").onclick = async () => {
    if (!view) return;
    const text = tableRows(view).map((r) => r.join("\t")).join("\n");
    try { await navigator.clipboard.writeText(text); }
    catch (e) { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
    setStatus("Spectra table copied: paste it into Excel or Word.", "ok");
  };

  const stem = () => "Spectra - " + [...(view ? view.groups.keys() : [])].slice(0, 3).join(", ").replace(/[\\/:*?"<>|]+/g, "");
  $("specPng").onclick = async () => {
    if (!view || !view.figure || !cdfitFiles.save) return;
    try { await cdfitFiles.save(stem() + ".png", await cdfitFiles.pngBlob(view.figure.svg, view.figure.width, view.figure.height)); }
    catch (e) { setStatus(e.message, "err"); }
  };
  $("specSvg").onclick = () => { if (view && view.figure && cdfitFiles.save) cdfitFiles.save(stem() + ".svg", view.figure.svg); };

  // θ at the wavelength against temperature, one column per peptide, into CD melting (which then fits Tm)
  function meltTable(v) {
    const names = [...v.groups.keys()];
    const temps = [...new Set(names.flatMap((n) => v.groups.get(n).map((r) => r.label.value)))].sort((a, b) => a - b);
    const lines = [[v.celsius ? "T (°C)" : "X", ...names].join("\t")];
    for (const t of temps)
      lines.push([String(t), ...names.map((n) => { const r = v.groups.get(n).find((q) => q.label.value === t); return r && isFinite(r.at) ? String(+r.at.toPrecision(8)) : ""; })].join("\t"));
    return lines.join("\n");
  }
  function sendToMelt() {
    if (!view || !view.trend) return;
    MODE_STORE.melt = meltState(view);   // the same state the section's fit used
    switchMode("melt");
    window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
  $("specToMelt").onclick = () => {
    const st = MODE_STORE.melt;
    const own = st && (st.dataText || "").trim() && st.dataText.trim() !== exampleData("melt").trim();
    if (own) { confirmRow.hidden = false; meltRow.hidden = true; return; }
    sendToMelt();
  };
  $("specYes").onclick = () => { confirmRow.hidden = true; sendToMelt(); };
  $("specNo").onclick = () => { confirmRow.hidden = true; meltRow.hidden = false; };

  let timer = null;
  lamInput.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 250); });
  CDFIT_AFTER_REFRESH.push(update);
  update();
  return { labelOf, valueAt, meltTable: () => (view && view.trend ? meltTable(view) : "") };
})();
