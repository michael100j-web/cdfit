"use strict";
/* Stacked graph panels on one x axis, in the add-in's graph style, for the page's sections below the app.
   opt = { xVals, xTitle, legendAt: "tl" | "tr", legend: [{label, color, dash, hollow}],
           panels: [{ title, height (fraction of the graph height), axis: {min, max, step} | null, zero,
                      lines: [{xs, ys, color, dash}], points: [{x, y, color, hollow}], vlines: [{x, color}] }] } */
function cdfitPanels(opt) {
  const F = S.fmt, fs = +F.fontSize || 16, fam = F.fontFamily || "Arial", tfs = fs * 1.06;
  const pw = +F.plotW || 430, ph = +F.plotH || 290, tick = fs * 0.45, minorTick = tick * 0.55;
  const aw = +F.axisW || 1.25, lw = +F.lineW > 0 ? +F.lineW : 2;
  const P = opt.panels, hs = P.map((p) => Math.round(ph * (p.height || 0.6))), gap = Math.ceil(fs * 1.25);
  const xa = makeAxis(opt.xVals, "", "", "", F.xMinor, false, !!opt.xPad);
  const str = (v) => (v === undefined || v === null ? "" : String(v));
  const ya = P.map((p) => {
    const vals = p.lines.flatMap((l) => l.ys).concat(p.points.map((q) => q.y)).filter(isFinite);
    const a = p.axis || {};
    return makeAxis(vals.length ? vals : [0, 1], str(a.min), str(a.max), str(a.step), 1, false, true);
  });
  const labW = Math.max(...ya.map((ax) => Math.max(...ax.ticks.map((v) => markupWidth(ax.label(v), fs, fam)))));
  const ml = Math.ceil(tick + 5 + labW + 10 + tfs * 1.05 + 8), mt = Math.ceil(fs * 0.7);
  const mr = Math.ceil(Math.max(12, markupWidth(xa.label(xa.ticks[xa.ticks.length - 1]), fs, fam) / 2 + 6));
  const mb = Math.ceil(tick + 5 + fs + 8 + tfs * 1.1 + 8);
  const tops = [];
  hs.forEach((h, k) => tops.push(k ? tops[k - 1] + hs[k - 1] + gap : mt));
  const W = ml + pw + mr, H = tops[tops.length - 1] + hs[hs.length - 1] + mb;
  const X = (v) => ml + xa.frac(v) * pw, f = (v) => v.toFixed(2);
  const dashAttr = (d) => (d ? ` stroke-dasharray="${d}"` : "");
  let s = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="${esc(fam)}" font-size="${fs}">`;
  s += `<rect width="${W}" height="${H}" fill="#ffffff"/><defs>`;
  tops.forEach((t, k) => { s += `<clipPath id="pclip${k}"><rect x="${ml}" y="${t - 2}" width="${pw + 2}" height="${hs[k] + 4}"/></clipPath>`; });
  s += "</defs>";
  P.forEach((p, k) => {
    const ax = ya[k], top = tops[k], h = hs[k], by = top + h, Y = (v) => top + h - ax.frac(v) * h;
    const last = k === P.length - 1;
    if (p.zero && ax.min < 0 && ax.max > 0)
      s += `<line x1="${ml}" y1="${f(Y(0))}" x2="${f(ml + pw)}" y2="${f(Y(0))}" stroke="#000000" stroke-width="${f(aw * 0.6)}" stroke-dasharray="3,3" opacity="0.55"/>`;
    for (const v of p.vlines || []) {
      if (v.x >= xa.min && v.x <= xa.max)
        s += `<line x1="${f(X(v.x))}" y1="${top}" x2="${f(X(v.x))}" y2="${f(by)}" stroke="${v.color}" stroke-width="1" stroke-dasharray="2,3" opacity="0.85"/>`;
    }
    s += `<g clip-path="url(#pclip${k})" fill="none" stroke-width="${lw}" stroke-linejoin="round">`;
    for (const l of p.lines) {
      let d = "";
      l.xs.forEach((x, i) => {
        const px = X(x), py = Y(l.ys[i]);
        if (isFinite(px) && isFinite(py)) d += (d ? "L" : "M") + f(px) + "," + f(Math.max(-1e4, Math.min(1e4, py)));
      });
      if (d) s += `<path d="${d}" stroke="${l.color}"${dashAttr(l.dash)}/>`;
    }
    s += "</g>";
    for (const q of p.points) {
      if (!isFinite(q.x) || !isFinite(q.y) || q.x < xa.min || q.x > xa.max || q.y < ax.min || q.y > ax.max) continue;
      const r = q.r || 2.6;
      s += `<circle cx="${f(X(q.x))}" cy="${f(Y(q.y))}" r="${r}" fill="${q.hollow ? "#ffffff" : q.color}" stroke="${q.color}" stroke-width="${q.hollow ? 1.2 : 0.5}" opacity="${q.opacity || 0.8}"/>`;
    }
    s += `<g stroke="#000000" stroke-width="${aw}" fill="none" stroke-linecap="square">`;
    s += `<line x1="${ml}" y1="${f(by)}" x2="${f(ml + pw)}" y2="${f(by)}"/><line x1="${ml}" y1="${top}" x2="${ml}" y2="${f(by)}"/>`;
    xa.ticks.forEach((v) => { s += `<line x1="${f(X(v))}" y1="${f(by)}" x2="${f(X(v))}" y2="${f(by + tick)}"/>`; });
    xa.minor.forEach((v) => { s += `<line x1="${f(X(v))}" y1="${f(by)}" x2="${f(X(v))}" y2="${f(by + minorTick)}"/>`; });
    ax.ticks.forEach((v) => { s += `<line x1="${ml}" y1="${f(Y(v))}" x2="${f(ml - tick)}" y2="${f(Y(v))}"/>`; });
    ax.minor.forEach((v) => { s += `<line x1="${ml}" y1="${f(Y(v))}" x2="${f(ml - minorTick)}" y2="${f(Y(v))}"/>`; });
    s += `</g><g fill="#000000">`;
    if (last) xa.ticks.forEach((v) => { s += `<text x="${f(X(v))}" y="${f(by + tick + 5 + fs * 0.78)}" text-anchor="middle">${markupTspans(xa.label(v), fs)}</text>`; });
    ax.ticks.forEach((v) => { s += `<text x="${f(ml - tick - 5)}" y="${f(Y(v) + fs * 0.36)}" text-anchor="end">${markupTspans(ax.label(v), fs)}</text>`; });
    const tx = ml - tick - 5 - labW - 10 - tfs * 0.25;
    s += `<text transform="translate(${f(tx)},${f(top + h / 2)}) rotate(-90)" x="0" y="0" text-anchor="middle" font-size="${f(tfs)}">${markupTspans(p.title, tfs)}</text>`;
    if (last) s += `<text x="${f(ml + pw / 2)}" y="${f(by + tick + 5 + fs + 8 + tfs * 0.8)}" text-anchor="middle" font-size="${f(tfs)}">${markupTspans(opt.xTitle, tfs)}</text>`;
    s += "</g>";
  });
  const items = opt.legend || [];
  if (items.length) {
    const lfs = fs * 0.8, lh = lfs * 1.45, sym = lfs * 2.2;   // labels are markup: escape names with cdfitMarkupEscape
    const wide = Math.max(...items.map((it) => markupWidth(it.label, lfs, fam)));
    const lx = opt.legendAt === "tr" ? ml + pw - 10 - sym - wide : ml + 14, ly = tops[0] + 8;
    s += `<g font-size="${f(lfs)}">`;
    items.forEach((it, k) => {
      const cy = ly + lh * k + lh / 2;
      s += `<line x1="${f(lx)}" y1="${f(cy)}" x2="${f(lx + sym * 0.8)}" y2="${f(cy)}" stroke="${it.color}" stroke-width="${lw}"${dashAttr(it.dash)}/>`;
      s += `<circle cx="${f(lx + sym * 0.4)}" cy="${f(cy)}" r="3" fill="${it.hollow ? "#ffffff" : it.color}" stroke="${it.color}" stroke-width="1.2"/>`;
      s += `<text x="${f(lx + sym)}" y="${f(cy + lfs * 0.36)}">${markupTspans(it.label, lfs)}</text>`;
    });
    s += "</g>";
  }
  return { svg: s + "</svg>", width: W, height: H };
}
