"use strict";
/* Open or drop several files at once: each file's data become columns of one table, matched by X.
   Spectrometer files are read as such. A JASCO export keeps its CD channel. A Chirascan (Pro-Data) CSV keeps its
   CircularDichroism block, or its Absorbance block in UV melting. From a scan at several wavelengths, or from
   spectra named with their temperatures, the melting modes take the signal at one wavelength (225 nm unless
   changed) against temperature, and CD spectrum mode takes one spectrum per temperature. */
const cdfitImport = (function () {
  const LAMBDA_KEY = "cdfit.page.lambda";
  const HT = /\b(?:HT|HV)\b|volt|dynode/i;   // detector voltage channels, not signal
  const WAVE_HINT = /nm\b|nanomet|wave\s*length|λ/i;
  const TEMP_HINT = /temp|°\s*C|℃|celsius|kelvin|^\s*T\s*(?:[([]|$)/i;
  const TIME_HINT = /time|\bmin\b|\bsec|\(s\)|\[s\]/i;

  async function readText(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    if (buf[0] === 0xff && buf[1] === 0xfe) return new TextDecoder("utf-16le").decode(buf);
    if (buf[0] === 0xfe && buf[1] === 0xff) return new TextDecoder("utf-16be").decode(buf);
    const utf8 = new TextDecoder("utf-8").decode(buf);
    if (!utf8.includes("\uFFFD")) return utf8.replace(/^\uFEFF/, "");
    try { return new TextDecoder("windows-1250").decode(buf); } catch (e) { return utf8; }
  }

  /* Excel files, read with SheetJS (loaded from cdnjs the first time one is opened): the first sheet, cells joined by
     tabs, numbers as JavaScript writes them, empty rows dropped, as the skill reads them. */
  let sheetJs = null;
  function loadSheetJs() {
    if (window.XLSX) return Promise.resolve(window.XLSX);
    sheetJs = sheetJs || new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
      s.onload = () => (window.XLSX ? resolve(window.XLSX) : reject(new Error("the Excel reader did not start")));
      s.onerror = () => { sheetJs = null; reject(new Error("the Excel reader could not be loaded")); };
      document.head.appendChild(s);
    });
    return sheetJs;
  }
  async function readXlsx(file) {
    const X = await loadSheetJs();
    const wb = X.read(new Uint8Array(await file.arrayBuffer()), { type: "array" });
    const rows = X.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1, raw: true, blankrows: false, defval: "" });
    return rows.map((r) => {
      const cells = r.map((v) => (v === null || v === undefined ? "" : typeof v === "number" ? String(v) : String(v).replace(/[\t\n]/g, " ")));
      while (cells.length && cells[cells.length - 1] === "") cells.pop();
      return cells.join("\t");
    }).filter((l) => l.trim()).join("\n");
  }
  const isExcel = (name) => /\.(xlsx|xlsm|xls)$/i.test(name);

  // one line's cells, split the way parseData splits a whole table
  const cellsOf = (l) => (l.includes("\t") ? l.split("\t") : l.includes(";") ? l.split(";")
    : /\d,\d/.test(l) && /\s/.test(l.trim()) ? l.trim().split(/\s+/) : l.trim().split(/[\s,]+/));

  // a comma-separated file as tab-separated, so that names with spaces ("CD 225 nm") stay whole
  function csvToTabs(text) {
    if (/[\t;]/.test(text)) return text;
    const lines = text.replace(/\r/g, "").split("\n"), data = lines.filter((l) => /^\s*[-+]?\.?\d/.test(l));
    if (!data.length || !data.every((l) => l.includes(",") && !/\S\s+\S/.test(l.trim().replace(/\s*,\s*/g, ",")))) return text;
    return lines.map((l) => splitCsv(l).join("\t")).join("\n");
  }
  function splitCsv(l) {
    const out = [];
    let cur = "", quoted = false;
    for (let i = 0; i < l.length; i++) {
      const ch = l[i];
      if (quoted) {
        if (ch !== '"') cur += ch;
        else if (l[i + 1] === '"') { cur += '"'; i++; }
        else quoted = false;
      } else if (ch === '"') quoted = true;
      else if (ch === ",") { out.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    out.push(cur.trim());
    return out;
  }

  /* JASCO text export: header lines, XYDATA, the data, then an extended-information block. An export of spectra at
     several temperatures starts its data with a row of temperatures under an empty first cell. */
  function jasco(text) {
    const lines = text.replace(/\r/g, "").split("\n");
    const start = lines.findIndex((l) => l.trim().toUpperCase() === "XYDATA");
    if (start < 0) return null;
    const head = {};
    for (const l of lines.slice(0, start)) {
      const m = /^([^\t,;]+)[\t,;](.*)$/.exec(l);
      if (m) head[m[1].trim().toUpperCase()] = m[2].trim();
    }
    const data = [];
    let cols = null;
    for (const l of lines.slice(start + 1)) {
      if (!l.trim()) continue;
      if (!data.length && !cols && /^[\t,;]/.test(l)) {
        const c = l.split(/[\t,;]/).slice(1).map((s) => s.trim()).filter((s) => s !== "");
        if (c.length && c.every((s) => isFinite(parseNum(s)))) { cols = c; continue; }
      }
      const cells = cellsOf(l.trim());
      if (isNaN(parseNum(cells[0]))) break;
      data.push(cells.map((s) => s.trim()).join("\t"));
    }
    const x = head.XUNITS || "X", xWave = WAVE_HINT.test(x);
    const temp = (c) => (xWave && parseNum(c) >= -30 && parseNum(c) <= 130 ? c + " °C" : c);   // spectra under their temperatures
    const names = cols ? [x, ...cols.map(temp)]
      : [x, head.YUNITS || "Y"].concat(["Y2UNITS", "Y3UNITS"].filter((k) => head[k]).map((k) => head[k]));
    return { text: [names.join("\t"), ...data].join("\n"), matrix: !!cols };
  }

  /* Chirascan (Applied Photophysics Pro-Data) CSV: "ProDataCSV", remarks such as "#Concentration: 200 uM", then
     after "Data:" one block per property (CircularDichroism, HV, Absorbance, …). A spectrum block is "Wavelength,",
     the property name, then wavelength,value rows. A scan block is the property name, "Temperature,Wavelength", a
     row of wavelengths under an empty first cell, then one row per temperature. Saved through Excel, the cells are
     tab-separated and "Wavelength," loses its comma. */
  function chirascan(text) {
    const lines = text.replace(/\r/g, "").split("\n");
    if ((lines.find((l) => l.trim()) || "").replace(/[,;\s]+$/, "").trim() !== "ProDataCSV") return null;
    const sep = /^[ ]*-?\d[^\n]*\t/m.test(text) ? "\t" : /^\s*-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*;/m.test(text) ? ";" : ",";
    const remark = (key) => {
      const l = lines.find((s) => s.trim().toLowerCase().startsWith("#" + key.toLowerCase() + ":"));
      return l ? l.trim().slice(key.length + 2).replace(/[,;\s]+$/, "").trim() : "";
    };
    const start = lines.findIndex((l) => /^\s*data\s*:?[\s,;]*$/i.test(l));
    const blocks = [];
    let cur = null, labels = [];
    const close = () => { if (cur && cur.rows.length) blocks.push(cur); cur = null; };
    for (const line of lines.slice(start + 1)) {
      const cells = line.split(sep).map((c) => c.trim());
      while (cells.length && cells[cells.length - 1] === "") cells.pop();
      if (!cells.length) { close(); continue; }
      const nums = cells.map(parseNum), rest = nums.slice(1);
      const numeric = rest.length > 0 && rest.some((v) => isFinite(v)) && cells.slice(1).every((c, k) => c === "" || isFinite(rest[k]));
      if (numeric && (cells[0] === "" || isFinite(nums[0]))) {
        if (!cur) {   // the text lines just above the numbers name the block: its property and its axes
          const plain = labels.filter((l) => !l.includes(sep)), prop = plain.pop() || "";
          const axes = (labels.filter((l) => l.includes(sep)).pop() || plain.pop() || "").split(sep).map((c) => c.trim()).filter(Boolean);
          cur = { property: prop, rowAxis: axes[0] || "", colAxis: axes[1] || "", cols: null, rows: [] };
          labels = [];
        }
        if (cells[0] === "") cur.cols = rest; else cur.rows.push(nums);
        continue;
      }
      close();
      if (/^history\s*:/i.test(cells[0])) break;
      labels.push(line.trim());
    }
    close();
    if (!blocks.length) return null;
    const t = /-?\d+(?:[.,]\d+)?/.exec(remark("Temperature"));
    return { blocks, description: remark("Description"), temperature: t ? parseNum(t[0]) : NaN };
  }

  // a wavelength in a column name: "225", "225 nm", "CD 225nm", "CD225", "A280"
  function nmIn(name) {
    const s = String(name).trim();
    let m = /(\d+(?:[.,]\d+)?)\s*nm(?![a-z])/i.exec(s);
    if (m) return { w: parseNum(m[1]), explicit: true, at: m.index, len: m[0].length };
    m = /^(?:CD|θ|theta|ellipticity|abs|absorbance|A|OD)\s*[@_=:-]?\s*(\d{3}(?:[.,]\d+)?)$/i.exec(s);
    if (m) return { w: parseNum(m[1]), explicit: true, at: s.length - m[1].length, len: m[1].length };
    const v = parseNum(s);
    return isFinite(v) ? { w: v, explicit: false, at: 0, len: s.length } : null;
  }
  // the name without its wavelength, or "" when only a channel word (CD, A, θ, a unit) is left
  function groupOf(name, hit) {
    const s = String(name).trim();
    const rest = (s.slice(0, hit.at) + s.slice(hit.at + hit.len)).replace(/^[\s_\-–,;:@=]+|[\s_\-–,;:@=]+$/g, "").trim();
    return /^(?:CD|θ|theta|ellipticity|signal|abs|absorbance|A|OD|mdeg)?\s*(?:\[[^\]]*\]|\([^)]*\))?$/i.test(rest) ? "" : rest;
  }

  // a wavelength axis: strictly monotonic, in the UV or visible; unlabelled numbers must look like a far-UV spectrum
  function waveAxis(v, hinted) {
    if (v.length < 2) return false;
    const up = v[1] > v[0];
    let lo = Infinity, hi = -Infinity, step = 0;
    for (let i = 0; i < v.length; i++) {
      if (!isFinite(v[i])) return false;
      if (i && !(up ? v[i] > v[i - 1] : v[i] < v[i - 1])) return false;
      if (i) step = Math.max(step, Math.abs(v[i] - v[i - 1]));
      lo = Math.min(lo, v[i]); hi = Math.max(hi, v[i]);
    }
    if (lo < 150 || hi > 1100) return false;
    return hinted || (v.length >= 5 && lo < 250 && step <= 10);
  }

  // where the wavelength is in a scan: measured, between two wavelengths at most 5 nm apart, or the only one
  function pickWave(waves, lam, single = true) {
    const k = waves.findIndex((w) => Math.abs(w - lam) < 1e-6);
    if (k >= 0) return { k };
    let lo = -1, hi = -1;
    waves.forEach((w, i) => {
      if (w < lam && (lo < 0 || w > waves[lo])) lo = i;
      if (w > lam && (hi < 0 || w < waves[hi])) hi = i;
    });
    if (lo >= 0 && hi >= 0 && waves[hi] - waves[lo] <= 5) return { lo, hi, u: (lam - waves[lo]) / (waves[hi] - waves[lo]) };
    return single && waves.length === 1 ? { k: 0, only: true } : null;
  }
  const valueOf = (row, pk) => (pk.lo === undefined ? row[pk.k] : row[pk.lo] + pk.u * (row[pk.hi] - row[pk.lo]));
  function waveList(waves) {
    const w = [...new Set(waves)].sort((a, b) => a - b), steps = w.slice(1).map((x, i) => x - w[i]);
    if (w.length >= 3 && steps.every((s) => Math.abs(s - steps[0]) < 1e-6))
      return `${fmtNum(w[0], 4)}–${fmtNum(w[w.length - 1], 4)} nm every ${fmtNum(steps[0], 3)} nm`;
    return w.map((x) => fmtNum(x, 4)).join(", ") + " nm";
  }

  /* What a file holds, for one mode. kind "scan": a signal at one or more wavelengths (across) against temperature
     (down); "spec": spectra, wavelengths down the first column; "melt": a melting curve; "table": anything else,
     used as it is; "none": nothing for this mode. */
  function describe(raw, stem, mode) {
    const c = chirascan(raw);
    if (c) return fromChirascan(c, stem, mode);
    const j = jasco(raw), text = j ? j.text : csvToTabs(raw), p = parseData(text);
    if (!p.rows.length || !p.names.length) return null;
    const onlyFirst = !!j && !j.matrix;
    return { file: stem, name: stem, source: j ? "JASCO" : "", p, onlyFirst, raw: text, ...layout(p, onlyFirst) };
  }

  function layout(p, onlyFirst) {
    const xs = p.rows.map((r) => r[0]);
    if (!TEMP_HINT.test(p.xName) && !TIME_HINT.test(p.xName) && waveAxis(xs, WAVE_HINT.test(p.xName))) return { kind: "spec" };
    if (onlyFirst) return { kind: "table" };
    const signal = p.names.map((name, j) => ({ name, j })).filter((c) => !HT.test(c.name));
    const hits = signal.map((c) => ({ ...c, hit: nmIn(c.name) })).filter((c) => c.hit && c.hit.w >= 150 && c.hit.w <= 1100);
    const tempHint = TEMP_HINT.test(p.xName) || p.xName === "";
    if (!hits.length || hits.length !== signal.length || !(tempHint || xs.every((x) => x >= -30 && x <= 130))) return { kind: "table" };
    const explicit = hits.some((c) => c.hit.explicit), groups = new Map();
    for (const c of hits) {
      const g = groupOf(c.name, c.hit);
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(c);
    }
    const list = [...groups].map(([name, cs]) => ({ name, waves: cs.map((c) => c.hit.w), js: cs.map((c) => c.j) }));
    if (list.some((g) => new Set(g.waves).size !== g.waves.length)) return { kind: "table" };
    // bare numbers count as wavelengths only under a temperature column and when the wavelength is among them
    if (!explicit && !(tempHint && list.some((g) => pickWave(g.waves, lambda(), false)))) return { kind: "table" };
    return { kind: "scan", temps: xs, groups: list.map((g) => ({ name: g.name, waves: g.waves, rows: p.rows.map((r) => g.js.map((j) => r[j + 1])) })) };
  }

  /* Points measured with the detector at its voltage limit carry no signal (a long cell or a strong absorber in the
     far UV): the cells of the HV block at 99.5% or more of its highest value, when that is at least 900 V. */
  function limits(c, b) {
    const hv = c.blocks.find((x) => /^(HV|HT)$/i.test(x.property) && x.rowAxis === b.rowAxis && x.colAxis === b.colAxis && x.rows.length === b.rows.length);
    if (!hv) return null;
    let top = -Infinity;
    for (const r of hv.rows) for (let k = 1; k < r.length; k++) if (isFinite(r[k])) top = Math.max(top, r[k]);
    return top >= 900 ? { top, at: (i, k) => hv.rows[i][k + 1] >= 0.995 * top } : null;
  }
  const limitNote = (name, n, top, where) =>
    `${name}: ${n} point${n > 1 ? "s" : ""} ${where} left out, measured with the detector at its limit (HV ${fmtNum(top, 4)} V).`;

  function fromChirascan(c, stem, mode) {
    const want = mode === "uv" ? /^absorbance$/i : /circular\s*dichroism|^CD$/i;
    const b = c.blocks.find((x) => want.test(x.property));
    const name = stem;   // the file's name: the #Description remark is often left from an earlier sample
    const base = { file: stem, name, source: "Chirascan", unit: b && /circular/i.test(b.property) ? "mdeg" : "", notes: [] };
    if (!b) return { ...base, kind: "none", why: mode === "uv" ? "no absorbance in the file" : "no CD in the file" };
    const rowWave = /wave/i.test(b.rowAxis), rowTemp = /temp/i.test(b.rowAxis);
    const colWave = /wave/i.test(b.colAxis), colTemp = /temp/i.test(b.colAxis);
    const lim = limits(c, b);
    if (!b.cols) {
      const pts = [], gone = [];
      b.rows.forEach((r, i) => { if (lim && lim.at(i, 0)) gone.push(r[0]); else pts.push([r[0], r[1]]); });
      if (gone.length) {
        const lo = Math.min(...gone), hi = Math.max(...gone), unit = rowWave ? " nm" : rowTemp ? " °C" : "";
        let note = limitNote(name, gone.length, lim.top, lo === hi ? `at ${fmtNum(lo, 4)}${unit}` : `from ${fmtNum(lo, 4)} to ${fmtNum(hi, 4)}${unit}`);
        if (rowWave && gone.some((w) => w >= 190 && w <= 205)) note = note.slice(0, -1) + ", so the band near 197 nm is lost: λmin and Rpn are not reliable.";
        base.notes.push(note);
      }
      if (rowWave) return { ...base, kind: "spec", spectra: [{ name: isFinite(c.temperature) ? `${name} (${c.temperature} °C)` : name, pts }] };
      return { ...base, kind: rowTemp ? "melt" : "table", cols: [{ name, pts }] };
    }
    const why = b.rows.map((r, i) => r.slice(1).map((_, k) => !!(lim && lim.at(i, k))));
    const rows = b.rows.map((r, i) => r.slice(1).map((v, k) => (why[i][k] ? NaN : v)));
    if (rowTemp && colWave) return { ...base, kind: "scan", top: lim ? lim.top : NaN, temps: b.rows.map((r) => r[0]), groups: [{ name: "", waves: b.cols, rows, why }] };
    const cut = why.flat().filter(Boolean);
    if (cut.length) base.notes.push(limitNote(name, cut.length, lim.top, "of the table"));
    const across = (label) => b.cols.map((v, k) => ({ name: label(v), pts: b.rows.map((r, i) => [r[0], rows[i][k]]) }));
    if (rowWave && colTemp) return { ...base, kind: "spec", spectra: across((t) => `${name} ${t} °C`) };
    return { ...base, kind: "table", cols: across((v) => `${name} ${v}`) };
  }

  // a plain or JASCO file's columns, named as they always were: by the file when it gives one column
  function plainCols(fd, many) {
    const p = fd.p, ny = fd.onlyFirst ? Math.min(1, p.names.length) : p.names.length, out = [];
    for (let j = 0; j < ny; j++) {
      if (fd.kind === "spec" && HT.test(p.names[j]) && !fd.onlyFirst) continue;
      const name = many || fd.source ? (ny === 1 ? fd.file : `${fd.file}: ${p.names[j]}`) : p.names[j];
      out.push({ name, pts: p.rows.filter((r) => isFinite(r[j + 1])).map((r) => [r[0], r[j + 1]]) });
    }
    return out;
  }
  const groupName = (fd, g, many) => (!g.name ? fd.name : many || fd.source ? `${fd.name}: ${g.name}` : g.name);

  function scanMelt(fd, lam, many) {
    const cols = [], notes = [], misses = [];
    for (const g of fd.groups) {
      const pk = pickWave(g.waves, lam), name = groupName(fd, g, many);
      if (!pk) { misses.push(g); continue; }
      const pts = fd.temps.map((t, i) => [t, valueOf(g.rows[i], pk)]);
      cols.push({ name, pts });
      if (g.why) {   // the temperatures left out at this wavelength
        const ks = pk.lo === undefined ? [pk.k] : [pk.lo, pk.hi], n = g.why.filter((w) => ks.some((k) => w[k])).length;
        if (n) notes.push(limitNote(name, n, fd.top, `at ${fmtNum(lam, 4)} nm`));
      }
      if (pk.only && Math.abs(g.waves[0] - lam) > 1e-6) notes.push(`${name}: measured at ${fmtNum(g.waves[0], 4)} nm only, so that is used.`);
    }
    const why = misses.length ? `no ${fmtNum(lam, 4)} nm: measured at ${waveList(misses[0].waves)}` : "";
    if (cols.length && misses.length) notes.push(`${fd.file}: ${why}.`);
    return { cols, notes, why };
  }
  function scanSpectra(fd, many) {
    const out = [];
    fd.temps.forEach((t, i) => {
      for (const g of fd.groups) out.push({ name: `${groupName(fd, g, many)} ${t} °C`, pts: g.waves.map((w, k) => [w, g.rows[i][k]]) });
    });
    return out;
  }
  // spectra from all files together (a peptide's spectra can come from several files): one column per peptide
  function spectraMelt(spectra, lam) {
    const groups = new Map();
    let labelled = 0;
    for (const s of spectra) {
      const lab = cdfitSpectra.labelOf(s.name);
      if (!lab || !isFinite(lab.value)) continue;
      labelled++;
      const v = cdfitSpectra.valueAt({ xs: s.pts.map((q) => q[0]), ys: s.pts.map((q) => q[1]) }, lam);
      if (!groups.has(lab.group)) groups.set(lab.group, new Map());
      const g = groups.get(lab.group);
      if (!g.has(lab.value)) g.set(lab.value, v);   // the first spectrum at a temperature counts
    }
    if (!(labelled >= 3 && [...groups.values()].some((g) => g.size >= 2)))
      return { cols: [], why: "spectra with no temperature series in their names" };
    const cols = [...groups].map(([name, g]) => ({ name, pts: [...g].sort((a, b) => a[0] - b[0]) })).filter((c) => c.pts.some((q) => isFinite(q[1])));
    return cols.length ? { cols, why: "" } : { cols, why: `${fmtNum(lam, 4)} nm is outside the spectra` };
  }

  // everything the files give in one mode
  function build(texts, mode, lam) {
    const out = { mode, cols: [], notes: [], skipped: [], used: [], picked: false, asIs: true, single: null, scans: [] };
    const fds = [];
    for (const t of texts) {
      const fd = describe(t.raw, t.stem, mode);
      if (fd) fds.push(fd); else out.skipped.push(`${t.stem} (no numbers)`);
    }
    const many = fds.length > 1, spectra = [];
    const use = (fd, cols) => { out.cols.push(...cols); out.used.push(fd); out.notes.push(...(fd.notes || [])); };
    for (const fd of fds) {
      if (fd.kind === "none") { out.skipped.push(`${fd.file} (${fd.why})`); continue; }
      if (fd.kind === "table") { use(fd, fd.cols || plainCols(fd, many)); if (fd.source) out.asIs = false; continue; }
      if (fd.kind === "melt") {
        if (mode === "spec") { out.skipped.push(`${fd.file} (a melting curve: open it in CD melting)`); continue; }
        use(fd, fd.cols); out.asIs = false; continue;
      }
      if (fd.kind === "scan") {
        out.asIs = false;
        if (mode === "spec") {
          if (fd.groups.some((g) => g.waves.length >= 10)) use(fd, scanSpectra(fd, many));
          else out.skipped.push(`${fd.file} (a melting scan at ${waveList(fd.groups[0].waves)}: open it in CD melting)`);
          continue;
        }
        const r = scanMelt(fd, lam, many);
        out.notes.push(...r.notes);
        if (!r.cols.length) { out.skipped.push(`${fd.file} (${r.why})`); continue; }
        use(fd, r.cols); out.picked = true; out.scans.push(fd);
        continue;
      }
      const named = fd.spectra || plainCols(fd, many);   // spectra
      if (fd.source) out.asIs = false;
      if (mode === "spec") use(fd, named);
      else spectra.push(...named.map((s) => ({ ...s, fd })));
    }
    if (spectra.length) {
      const r = spectraMelt(spectra, lam), from = [...new Set(spectra.map((s) => s.fd))];
      if (r.cols.length) {
        out.cols.push(...r.cols); out.used.push(...from); out.asIs = false; out.picked = true;
        for (const fd of from) out.notes.push(...(fd.notes || []));
      }
      else for (const fd of from) out.skipped.push(`${fd.file} (${r.why}: open ${from.length > 1 ? "them" : "it"} in CD spectrum)`);
    }
    if (fds.length === 1 && out.used.length === 1 && out.asIs && !fds[0].source) out.single = fds[0].raw;
    out.unit = out.used.length && out.used.every((fd) => fd.unit === "mdeg") ? "mdeg" : "";
    return out;
  }

  // one table from columns, matched by X
  function table(xName, cols) {
    const xs = new Map(), key = (x) => Math.round(x * 1e6) / 1e6, seen = new Map();
    const maps = cols.map((c) => {
      const m = new Map();
      for (const [x, y] of c.pts) if (isFinite(x) && isFinite(y)) { const k = key(x); m.set(k, y); xs.set(k, x); }
      return m;
    });
    const names = cols.map((c) => {   // the same name twice gets a number
      const n = c.name.replace(/[\t\r\n]+/g, " "), k = (seen.get(n) || 0) + 1;
      seen.set(n, k);
      return k > 1 ? `${n} (${k})` : n;
    });
    const keys = [...xs.keys()].sort((a, b) => a - b);
    const out = [[xName, ...names].join("\t")];
    for (const k of keys) out.push([String(xs.get(k)), ...maps.map((m) => (m.has(k) ? String(m.get(k)) : ""))].join("\t"));
    return out.join("\n");
  }

  const xNameFor = (name, mode) => {
    if (/nanomet|^\s*λ|wavelength/i.test(name || "")) return "λ (nm)";
    if (/temp|°c/i.test(name || "")) return "T (°C)";
    return name && name !== "X" ? name : { spec: "λ (nm)", melt: "T (°C)", uv: "T (°C)" }[mode] || "X";
  };

  // the y-axis title follows the wavelength and the unit, unless it was changed by hand
  function retitle(plan, lam) {
    const cur = S.fmt.yTitle || "";
    const auto = cur === modeFmt(S.mode).yTitle || /^\*(?:θ|A)\*(?:_\{[\d.]+\})?(?: \((?:mdeg|10\^\{3\} deg cm\^\{2\} dmol\^\{-1\})\))?$/.test(cur);
    if (!auto) return;
    const sub = `_{${fmtNum(lam, 4)}}`;
    let t = cur;
    if (S.mode === "uv") { if (plan.picked) t = `*A*${sub}`; }
    else if (S.mode === "spec") { if (plan.unit === "mdeg") t = "*θ* (mdeg)"; }
    else if (plan.unit === "mdeg") t = `*θ*${plan.picked ? sub : ""} (mdeg)`;
    else if (plan.picked) t = cur.replace(/^\*θ\*(?:_\{[\d.]+\})?/, `*θ*${sub}`);
    S.fmt.yTitle = t;
    $("yTitle").value = t;
  }

  // file names in natural order (CMP1_4C before CMP1_20C), the same order as the skill's
  const natural = (name) => name.replace(/\.[^.]+$/, "").toLowerCase().split(/(\d+)/).map((t, i) => (i % 2 ? Number(t) : t));
  function byName(a, b) {
    const x = natural(a.name), y = natural(b.name);
    for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
    return x.length - y.length;
  }

  let last = null;   // the last files read, to read them again at another wavelength
  async function load(files) {
    files = [...files].filter((f) => f && f.size > 0).sort(byName);
    if (!files.length) return;
    setStatus(`Reading ${files.length} file${files.length > 1 ? "s" : ""}…`);
    const texts = [], unread = [];
    for (const f of files) {
      try { texts.push({ stem: f.name.replace(/\.[^.]+$/, ""), raw: isExcel(f.name) ? await readXlsx(f) : await readText(f) }); }
      catch (e) { unread.push(`${f.name} (${(e && e.message) || "could not be read"})`); }
    }
    const lam = lambda(), from = S.mode;
    // the current mode if any file suits it, otherwise the mode the files are for
    let plan = null;
    for (const mode of [from, ...(from === "spec" ? ["melt"] : ["spec", "melt"])].filter((m, i, a) => a.indexOf(m) === i)) {
      const p = build(texts, mode, lam);
      if (p.cols.length) { plan = p; break; }
      plan = plan || p;
    }
    const skipped = [...unread, ...plan.skipped];
    if (!plan.cols.length) { setStatus(`Nothing to load: ${skipped.join("; ") || "no numbers found"}.`, "err"); return; }
    if (plan.mode !== from) switchMode(plan.mode);
    const xName = plan.asIs ? xNameFor(plan.used[0].p ? plan.used[0].p.xName : "", plan.mode) : plan.mode === "spec" ? "λ (nm)" : "T (°C)";
    const text = plan.single != null ? plan.single : table(xName, plan.cols);
    S.dataText = text; S.series = []; $("data").value = text;
    retitle(plan, lam);
    refresh(true);
    last = { files, text, mode: plan.mode, picked: plan.picked };

    const parts = [], n = plan.used.length, sig = plan.mode === "uv" ? "absorbance" : "CD";
    if (plan.mode !== from) {
      const they = n > 1 ? "they" : "it";
      parts.push(plan.mode === "spec" ? `${n > 1 ? "These files hold" : "This file holds"} spectra, so ${they} opened in CD spectrum.`
        : from === "uv" ? `No absorbance in ${n > 1 ? "these files" : "this file"}, so ${they} opened in CD melting.`
        : `${n > 1 ? "These files are melting scans" : "This file is a melting scan"}, so ${they} opened in CD melting.`);
    }
    if (plan.picked) {
      const one = plan.scans.length === 1 && n === 1 ? plan.scans[0] : null;
      const detail = one ? ` (${one.source ? one.source + " " : ""}scan at ${waveList(one.groups[0].waves)}, ${one.temps.length} temperatures)` : "";
      parts.push(`${n === 1 ? plan.used[0].name : n + " files"}: ${sig} at ${fmtNum(lam, 4)} nm against temperature${detail}.`);
    } else {
      const k = plan.cols.length;
      parts.push(`Loaded ${n} file${n > 1 ? "s" : ""} as ${k} data set${k > 1 ? "s" : ""}.`);
    }
    parts.push(...plan.notes);
    if (skipped.length) parts.push(`Skipped: ${skipped.join("; ")}.`);
    const tm = $("status").textContent;
    if (/^Tm = /.test(tm)) parts.push(tm + ".");
    setStatus(parts.join(" "), skipped.length || plan.notes.length ? "err" : "ok");
  }

  // the Data tab's file button takes several files
  const input = $("file");
  input.multiple = true;
  input.accept = ".csv,.txt,.tsv,.dat,.asc,.prn,.xlsx,.xlsm,.xls,text/plain";
  input.onchange = async () => { const fs = [...input.files]; input.value = ""; await load(fs); };
  $("btnFile").textContent = "Open files…";
  const tip = document.createElement("div");
  tip.className = "hint";
  tip.textContent = "Open or drop several files at once: each becomes a column, matched by X. Chirascan, JASCO and Excel files work. "
    + "From a scan at several wavelengths, or spectra named with their temperatures, CD and UV melting take the value at this wavelength:";
  const lamRow = document.createElement("div");
  lamRow.className = "row imp-lambda";
  lamRow.innerHTML = '<label for="impLambda">Wavelength</label><input type="number" id="impLambda" step="any" min="150" max="1100" value="225"><span>nm</span>';
  $("btnFile").closest(".row").after(tip);
  tip.after(lamRow);
  const lamInput = $("impLambda"), specLambda = $("specLambda");
  function lambda() { const v = parseNum(lamInput.value); return isFinite(v) && v > 0 ? v : 225; }
  try { const v = localStorage.getItem(LAMBDA_KEY); if (v && isFinite(parseNum(v))) { lamInput.value = v; if (specLambda) specLambda.value = v; } } catch (e) {}
  let timer = null;
  lamInput.addEventListener("input", () => {
    try { localStorage.setItem(LAMBDA_KEY, lamInput.value); } catch (e) {}
    if (specLambda && specLambda.value !== lamInput.value) { specLambda.value = lamInput.value; specLambda.dispatchEvent(new Event("input")); }
    clearTimeout(timer);
    timer = setTimeout(() => { if (last && last.picked && S.mode === last.mode && S.dataText === last.text) load(last.files); }, 400);
  });
  if (specLambda) specLambda.addEventListener("input", () => {
    if (lamInput.value === specLambda.value) return;
    lamInput.value = specLambda.value;
    try { localStorage.setItem(LAMBDA_KEY, lamInput.value); } catch (e) {}
  });

  // files dropped anywhere on the page
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  let depth = 0;
  document.addEventListener("dragenter", (e) => { if (hasFiles(e)) { depth++; document.body.classList.add("dropping"); } });
  document.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; document.body.classList.remove("dropping"); } });
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    document.body.classList.remove("dropping");
    load(e.dataTransfer.files);
  });

  return { load, jasco, chirascan, describe, build, table, lambda };
})();
