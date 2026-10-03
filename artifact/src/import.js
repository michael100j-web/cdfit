"use strict";
/* Open or drop several files at once: each file's data become columns of one table, matched by X.
   JASCO exports keep only their first channel (CD), named after the file. */
const cdfitImport = (function () {
  async function readText(file) {
    const buf = new Uint8Array(await file.arrayBuffer());
    if (buf[0] === 0xff && buf[1] === 0xfe) return new TextDecoder("utf-16le").decode(buf);
    if (buf[0] === 0xfe && buf[1] === 0xff) return new TextDecoder("utf-16be").decode(buf);
    const utf8 = new TextDecoder("utf-8").decode(buf);
    if (!utf8.includes("\uFFFD")) return utf8.replace(/^\uFEFF/, "");
    try { return new TextDecoder("windows-1250").decode(buf); } catch (e) { return utf8; }
  }

  // JASCO text export: header lines, then XYDATA, then the data, then an extended-information block
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
    for (const l of lines.slice(start + 1)) {
      if (!l.trim()) continue;
      if (isNaN(parseNum(l.trim().split(/[\t,; ]+/)[0]))) break;
      data.push(l);
    }
    const names = [head.XUNITS || "X", head.YUNITS || "Y"].concat(["Y2UNITS", "Y3UNITS"].filter((k) => head[k]).map((k) => head[k]));
    return [names.join("\t"), ...data].join("\n");
  }

  const xNameFor = (name) => {
    if (/nanomet|^\s*λ|wavelength/i.test(name || "")) return "λ (nm)";
    if (/temp|°c/i.test(name || "")) return "T (°C)";
    return name && name !== "X" ? name : { spec: "λ (nm)", melt: "T (°C)", uv: "T (°C)" }[S.mode] || "X";
  };

  function merge(parsed) {
    const cols = [], xs = new Map(), key = (x) => Math.round(x * 1e6) / 1e6;
    for (const { file, p, onlyFirst } of parsed) {
      const ny = onlyFirst ? Math.min(1, p.names.length) : p.names.length;
      for (let j = 0; j < ny; j++) {
        const map = new Map();
        for (const r of p.rows) {
          const v = r[j + 1];
          if (isFinite(v)) { const k = key(r[0]); map.set(k, v); xs.set(k, r[0]); }
        }
        cols.push({ name: (ny === 1 ? file : file + ": " + p.names[j]).replace(/[\t\r\n]+/g, " "), map });
      }
    }
    const keys = [...xs.keys()].sort((a, b) => a - b);
    const out = [[xNameFor(parsed[0].p.xName), ...cols.map((c) => c.name)].join("\t")];
    for (const k of keys) out.push([String(xs.get(k)), ...cols.map((c) => (c.map.has(k) ? String(c.map.get(k)) : ""))].join("\t"));
    return { text: out.join("\n"), columns: cols.length };
  }

  async function load(files) {
    files = [...files].filter((f) => f && f.size > 0)
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));   // 4C before 20C
    if (!files.length) return;
    setStatus(`Reading ${files.length} file${files.length > 1 ? "s" : ""}…`);
    const parsed = [], skipped = [];
    for (const f of files) {
      try {
        const raw = await readText(f), j = jasco(raw), p = parseData(j || raw);
        if (!p.rows.length || !p.names.length) { skipped.push(f.name); continue; }
        parsed.push({ file: f.name.replace(/\.[^.]+$/, ""), p, raw, onlyFirst: !!j });
      } catch (e) { skipped.push(f.name); }
    }
    if (!parsed.length) { setStatus(`No numbers found in ${skipped.join(", ")}.`, "err"); return; }
    let text, columns;
    if (parsed.length === 1 && !parsed[0].onlyFirst) { text = parsed[0].raw; columns = parsed[0].p.names.length; }
    else ({ text, columns } = merge(parsed));
    S.dataText = text; S.series = []; $("data").value = text;
    refresh(true);
    const skip = skipped.length ? ` Skipped (no numbers): ${skipped.join(", ")}.` : "";
    setStatus(`Loaded ${parsed.length} file${parsed.length > 1 ? "s" : ""} as ${columns} data set${columns > 1 ? "s" : ""}.${skip}`, skipped.length ? "err" : "ok");
  }

  // the Data tab's file button takes several files
  const input = $("file");
  input.multiple = true;
  input.accept = ".csv,.txt,.tsv,.dat,.asc,.prn,text/plain";
  input.onchange = async () => { const fs = [...input.files]; input.value = ""; await load(fs); };
  $("btnFile").textContent = "Open files…";
  const tip = document.createElement("div");
  tip.className = "hint";
  tip.textContent = "Open or drop several files at once: each becomes a column, matched by X. JASCO exports work.";
  $("btnFile").closest(".row").after(tip);

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

  return { load, merge, jasco };
})();
