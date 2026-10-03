"""Build artifact/cdfit.html, CD Fit as a page inside Claude (a claude.ai Artifact), from src/taskpane.html.

The page runs the add-in's own script unchanged: the same parser, fitter, graph and results. This script only
swaps the add-in's Word task-pane shell for a full-page layout with light and dark themes, saves the graph through
the viewer (`downloads`) and adds an optional "Ask Claude about this fit" panel (`sample`).

  py tools/build_artifact.py            write artifact/cdfit.html
  py tools/build_artifact.py --check    also load it in headless Edge/Chrome and check that the example fits

Publish with the Artifact tool: icon "chart", capabilities {"downloads": true, "sample": {}}.
"""
import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "taskpane.html"
OUT = ROOT / "artifact" / "cdfit.html"

HEAD = """<title>CD Fit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
/* Layout: a lab bench. The graph is the instrument's display (left, held in view on wide screens);
   the controls are its panel (right); on phones the panel follows the graph. */
:root {
  --bg: #f2f5f5;
  --surface: #ffffff;
  --sunken: #e8eeee;
  --field: #ffffff;
  --fg: #16232a;
  --muted: #586a70;
  --border: #d2dcdd;
  --accent: #0f6466;
  --accent-ink: #ffffff;
  --accent-soft: #dcebeb;
  --err: #b42318;
  --ok: #18794e;
  --paper: #ffffff;
  --paper-edge: #cfd9da;
  --shadow: 0 1px 2px rgb(16 40 44 / 6%), 0 10px 28px -16px rgb(16 40 44 / 28%);
  --badge-bg: #fff3d1;
  --badge-fg: #6b4e00;
  --badge-edge: #ecd58f;
  --font-ui: "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, sans-serif;
  --font-data: "IBM Plex Mono", Consolas, "Cascadia Mono", ui-monospace, monospace;
  --radius: 6px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0e1517; --surface: #152024; --sunken: #1b292d; --field: #101b1e; --fg: #e2ebeb; --muted: #94a7ab;
    --border: #2b3c41; --accent: #5ec2bd; --accent-ink: #052625; --accent-soft: #173638; --err: #ff8f85;
    --ok: #6fd39a; --paper: #ffffff; --paper-edge: #2b3c41; --shadow: 0 1px 2px rgb(0 0 0 / 30%), 0 12px 30px -14px rgb(0 0 0 / 60%);
    --badge-bg: #3a2f12; --badge-fg: #f3d58a; --badge-edge: #5a4818; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #0e1517; --surface: #152024; --sunken: #1b292d; --field: #101b1e; --fg: #e2ebeb; --muted: #94a7ab;
  --border: #2b3c41; --accent: #5ec2bd; --accent-ink: #052625; --accent-soft: #173638; --err: #ff8f85;
  --ok: #6fd39a; --paper: #ffffff; --paper-edge: #2b3c41; --shadow: 0 1px 2px rgb(0 0 0 / 30%), 0 12px 30px -14px rgb(0 0 0 / 60%);
  --badge-bg: #3a2f12; --badge-fg: #f3d58a; --badge-edge: #5a4818; color-scheme: dark;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 14px/1.45 var(--font-ui); padding-inline: clamp(16px, 3vw, 32px); padding-block: 0 32px; }
h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
.top { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px 20px; padding-block: 16px 14px; }
.brand { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-width: 0; }
.brand svg { color: var(--accent); flex: none; }
.host { font-size: 12px; color: var(--muted); }
#modes { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface); }
#modes button { border: 0; border-right: 1px solid var(--border); border-radius: 0; padding: 7px 14px; font-weight: 500; color: var(--muted); background: transparent; }
#modes button:last-child { border-right: 0; }
#modes button.active { background: var(--accent); color: var(--accent-ink); }
.app { display: grid; gap: 20px; grid-template-columns: minmax(0, 1fr); align-items: start; }
@media (min-width: 900px) {
  .app { grid-template-columns: minmax(0, 1fr) minmax(330px, 430px); }
  .stage { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 12px); }
}
.stage { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.paper { margin: 0; background: var(--paper); border: 1px solid var(--paper-edge); border-radius: var(--radius); padding: 14px 16px 8px; box-shadow: var(--shadow); }
#preview svg { width: 100%; height: auto; display: block; }
#preview .pt { cursor: pointer; }
#preview .pt:hover > * { stroke: #000000; stroke-width: 1.5; }
.badge { align-self: flex-start; font-size: 12px; color: var(--badge-fg); background: var(--badge-bg); border: 1px solid var(--badge-edge); border-radius: 999px; padding: 2px 10px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
button { font: inherit; font-weight: 500; padding: 7px 12px; border: 1px solid var(--border); background: var(--surface); color: var(--fg); border-radius: var(--radius); cursor: pointer; }
button:hover { border-color: var(--accent); }
button:disabled { opacity: 0.55; cursor: default; }
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
button.small { padding: 3px 9px; font-size: 12.5px; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.word-only, #linked { display: none !important; }
body.nofit #btnFit { display: none; }
#status { font-size: 13px; color: var(--muted); min-height: 20px; font-variant-numeric: tabular-nums; }
#status.err { color: var(--err); }
#status.ok { color: var(--ok); }
.ask { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); padding: 12px 14px; display: grid; gap: 8px; }
.ask h2 { font-size: 14px; margin: 0; font-weight: 600; }
.ask-head { display: flex; justify-content: space-between; align-items: baseline; gap: 4px 12px; flex-wrap: wrap; }
.ask-out { white-space: pre-wrap; font-size: 13.5px; line-height: 1.55; max-width: 72ch; }
.ask-out:empty { display: none; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); min-width: 0; }
nav.tabs { display: flex; gap: 2px; padding: 0 8px; border-bottom: 1px solid var(--border); position: sticky; top: env(safe-area-inset-top, 0px); background: var(--surface); z-index: 2; border-radius: var(--radius) var(--radius) 0 0; overflow-x: auto; }
nav.tabs button { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: none; padding: 10px 10px 8px; color: var(--muted); }
nav.tabs button.active { border-bottom-color: var(--accent); color: var(--fg); font-weight: 600; }
section.tab { display: none; padding: 12px 14px 20px; }
section.tab.active { display: block; }
h3 { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin: 16px 0 6px; font-weight: 600; }
h3:first-child { margin-top: 2px; }
textarea { width: 100%; font: 12.5px/1.4 var(--font-data); border: 1px solid var(--border); border-radius: var(--radius); padding: 7px 8px; resize: vertical; color: var(--fg); background: var(--field); }
input[type=number], input[type=text], select { font: inherit; padding: 5px 7px; border: 1px solid var(--border); border-radius: var(--radius); width: 100%; min-width: 0; background: var(--field); color: var(--fg); }
input[type=color] { width: 30px; height: 26px; padding: 0; border: 1px solid var(--border); border-radius: 4px; background: var(--field); }
.row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; }
.grid4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; align-items: end; }
label.f { display: flex; flex-direction: column; font-size: 12px; color: var(--muted); gap: 3px; min-width: 0; }
label.c { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
.hint { font-size: 12px; color: var(--muted); }
.msg { font-size: 12.5px; margin-top: 4px; }
.msg.err { color: var(--err); }
#styleList, #results, #paramTable { overflow-x: auto; }
table.t { border-collapse: collapse; width: 100%; font-size: 12.5px; font-variant-numeric: tabular-nums; }
table.t th, table.t td { border-bottom: 1px solid var(--border); padding: 4px 5px; text-align: left; }
table.t th { color: var(--muted); font-weight: 500; }
table.t td.num, table.t th.num { text-align: right; }
table.t input[type=text] { padding: 3px 5px; }
.series-item { display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 4px 0; }
.card { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 10px; background: var(--surface); }
.card h4 { margin: 0 0 6px; font-size: 13.5px; display: flex; align-items: center; gap: 8px; }
.swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.big { font-size: 18px; font-weight: 600; margin: 2px 0 8px; font-variant-numeric: tabular-nums; }
details summary { cursor: pointer; color: var(--accent); margin-top: 12px; }
code { font-family: var(--font-data); font-size: 12px; background: var(--sunken); padding: 0 4px; border-radius: 3px; }
@media (max-width: 520px) { .grid4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
"""

TOP = """<header class="top">
  <div class="brand">
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><path d="M3 3v26h26" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M6 9c6 0 7 1 10 8s5 7 12 7" fill="none" stroke="currentColor" stroke-width="2.2"/><circle cx="9" cy="9" r="2" fill="currentColor"/><circle cx="16" cy="16" r="2" fill="currentColor"/><circle cx="24" cy="23" r="2" fill="currentColor"/></svg>
    <h1>CD Fit</h1>
    <span class="host" id="hostLabel">Same fit as the Word add-in, v{version}</span>
  </div>
  {modes}
</header>
<main class="app">
<div class="stage">
<span class="badge" id="exampleBadge" hidden>Example data: paste your own in the Data tab</span>
<figure class="paper"><div id="preview"></div></figure>
"""

ASK = """<section class="ask" id="ask" hidden aria-labelledby="askTitle">
  <div class="ask-head"><h2 id="askTitle">Ask Claude about this fit</h2><span class="hint">Sends the data and results. Uses your Claude usage.</span></div>
  <label class="f" for="askQ">Question (optional)<textarea id="askQ" rows="2" placeholder="Is this fit trustworthy, and is there anything I should change?"></textarea></label>
  <div class="row"><button class="primary" id="askBtn">Ask Claude</button><button id="askStop" hidden>Stop</button><span class="hint" id="askNote"></span></div>
  <div class="ask-out" id="askOut" aria-live="polite"></div>
</section>
"""

EXTRA = r"""<script>
"use strict";
/* Page additions around the add-in's script: files saved through the viewer, Ask Claude, the example-data note. */
(function () {
  const cl = window.claude && typeof window.claude.use === "function" ? window.claude : null;
  const use = (name) => (cl ? cl.use(name).catch(() => null) : Promise.resolve(null));

  // Note while the example data is loaded
  const examples = {};
  const badge = $("exampleBadge");
  const markExample = () => {
    if (!(S.mode in examples)) examples[S.mode] = exampleData(S.mode).trim();
    badge.hidden = (S.dataText || "").trim() !== examples[S.mode];
  };
  const baseRefresh = refresh;
  refresh = function (refit) { baseRefresh(refit); markExample(); };
  markExample();

  $("btnCopyTop").onclick = () => $("btnCopy").click();

  // PNG and SVG, saved through the viewer, which asks the viewer to confirm each file
  const pngBtn = $("btnPng"), svgBtn = $("btnSvg");
  pngBtn.hidden = svgBtn.hidden = true;
  const fileStem = () => {
    const names = (DATA ? DATA.series : []).filter((s) => S.series[s.idx] && S.series[s.idx].visible).map((s) => s.name);
    const base = { melt: "CD melt", spec: "CD spectrum", uv: "UV melt" }[S.mode] || "CD Fit";
    return (base + (names.length ? " - " + names.slice(0, 3).join(", ") : "")).replace(/[\\/:*?"<>|]+/g, "").slice(0, 80);
  };
  const svgToPngBlob = (svg, w, h, scale) => new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = Math.round(w * scale); c.height = Math.round(h * scale);
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      c.toBlob((b) => (b ? resolve(b) : reject(new Error("The PNG could not be made."))), "image/png");
    };
    img.onerror = () => reject(new Error("The PNG could not be made."));
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  });
  use("downloads").then((downloads) => {
    if (!downloads) return;
    pngBtn.hidden = svgBtn.hidden = false;
    const gone = ["unavailable", "not_granted", "capability_disabled", "capability_removed"];
    const save = async (filename, data) => {
      try {
        await downloads.save({ filename, data });
        setStatus("Saved " + filename + ".", "ok");
      } catch (e) {
        const code = e && e.code;
        if (code === "declined") return;
        if (gone.includes(code)) { pngBtn.hidden = svgBtn.hidden = true; setStatus("Saving files is not available in this view.", "err"); return; }
        setStatus(code === "rate_limited" ? "Another save is waiting for your answer." : "The file could not be saved.", "err");
      }
    };
    pngBtn.onclick = async () => {
      if (!DATA || !DATA.series.length) { setStatus("Add data first.", "err"); return; }
      const { svg, width, height } = renderSVG();
      const dpi = S.fmt.exportFmt === "png600" ? 600 : 300, cm = +S.fmt.exportCm || 12;
      try { await save(fileStem() + ".png", await svgToPngBlob(svg, width, height, (cm / 2.54 * dpi) / width)); }
      catch (e) { setStatus(e.message, "err"); }
    };
    svgBtn.onclick = () => {
      if (!DATA || !DATA.series.length) { setStatus("Add data first.", "err"); return; }
      save(fileStem() + ".svg", renderSVG().svg);
    };
  });

  // Ask Claude about this fit (the viewer's own Claude, on a click)
  const RULES = [
    "You are helping a scientist judge a fit made in CD Fit, a tool for circular dichroism (CD) and UV melting curves and CD spectra of collagen model peptides (CMPs).",
    "In the default CMP model the triple helix (a trimer) melts into 3 monomers with ΔH fixed at -500 kJ/mol and sloping baselines; Tm is the midpoint at the measured concentration, and REFN/DEN and REFU/DEU are the native and unfolded baselines (intercept and slope per kelvin).",
    "Check the results against the data: baseline drift or artefacts the model cannot follow, a transition cut off at the edge of the data, poorly defined baselines, a step in the wrong direction (CD at 225 nm falls on unfolding, UV absorbance rises), residual scatter (Sy.x) larger than the point-to-point noise, parameters with huge errors.",
    "Answer in plain text without Markdown headings, at most 150 words: a one-line verdict, then only the points that matter, each with a concrete fix using the page's controls (Data tab: Exclude X outside; Model tab: Transition direction, fixing a parameter, another preset). Do not repeat the whole results table and do not invent measurements.",
  ].join(" ");
  const DEFAULT_Q = "Is this fit trustworthy, and is there anything I should change?";
  const fitContext = () => {
    const out = ["Mode: " + (MODES[S.mode] || MODES.melt).label + "."];
    if (S.fit && MODEL) {
      const preset = Object.keys(PRESETS).find((k) => PRESETS[k].text.trim() === S.eqText.trim());
      out.push("Model: " + (preset ? PRESETS[preset].label : "custom equation") + ". Equation in Prism syntax (X in the first data column):\n" + S.eqText.trim());
      const dir = { up: "the signal must rise on unfolding", down: "the signal must fall on unfolding" }[S.stepDir];
      out.push("Transition direction constraint: " + (dir || "none, either direction") + ".");
      const set = Object.entries(S.params || {}).filter(([, c]) => c && (c.fixed || String(c.value || "").trim() !== ""));
      if (set.length) out.push("Parameter settings: " + set.map(([k, c]) => k + (c.fixed ? " fixed at " : " starts at ") + c.value).join("; ") + ".");
    } else if (S.fit) {
      out.push("The equation has an error, so nothing was fitted.");
    } else {
      out.push("No model is fitted: the page reports spectrum features (maximum, minimum, zero crossing, Rpn = max/|min|).");
    }
    if (S.xFrom !== "" || S.xTo !== "") out.push("Only points with X from " + (S.xFrom === "" ? "the start" : S.xFrom) + " to " + (S.xTo === "" ? "the end" : S.xTo) + " are fitted; the rest are shown faded.");
    const mult = parseFloat(S.yMult);
    if (isFinite(mult) && mult !== 1) out.push("Y values were multiplied by " + S.yMult + ".");
    if (DATA && DATA.series.length) {
      out.push("Results as the page reports them (tab-separated):\n" + resultsMatrix().map((r) => r.join("\t")).join("\n"));
      const notes = [];
      DATA.series.forEach((s, j) => {
        const f = FITS[j];
        if (!f || !S.series[j] || !S.series[j].visible) return;
        if (f.error) { notes.push(s.name + ": the fit failed (" + f.error + ")."); return; }
        if (f.avoided) notes.push(s.name + ": without the direction constraint the fit " + (f.avoided.outside ? "puts Tm outside the data" : "has the opposite step") + " (Tm " + fmtNum(f.avoided.tm, 4) + " °C).");
        if (f.limit) notes.push(s.name + ": the best allowed fit lies on the constraint, so Tm has no standard error.");
        if (!f.converged) notes.push(s.name + ": the fit did not converge.");
        if (f.ambiguous) notes.push(s.name + ": the parameters are not identifiable.");
      });
      if (notes.length) out.push("Warnings shown on the page:\n" + notes.join("\n"));
      const text = S.dataText.length > 12000 ? S.dataText.slice(0, 12000) + "\n[rest of the data cut off]" : S.dataText;
      out.push("The data as entered (first column X, then one column per data set):\n" + text);
    }
    return out.join("\n\n");
  };
  const ASK_COPY = {
    rate_limited: "Too many requests right now. Try again in a minute.",
    session_expired: "Sign in to Claude again, then ask again.",
    refused: "Claude declined this request. Try a different question.",
    empty_completion: "Claude returned no answer. Try a shorter question.",
    prompt_too_large: "The data are too long to send. Exclude some points or columns, then ask again.",
  };
  const askBox = $("ask"), askBtn = $("askBtn"), stopBtn = $("askStop"), askOut = $("askOut"), askNote = $("askNote");
  use("sample").then((sample) => {
    if (!sample) return;
    askBox.hidden = false;
    let ctl = null;
    stopBtn.onclick = () => { if (ctl) ctl.abort(); };
    askBtn.onclick = async () => {
      if (!DATA || !DATA.series.length) { askNote.textContent = "Add data first."; return; }
      ctl = new AbortController();
      askBtn.disabled = true; stopBtn.hidden = false; askNote.textContent = "";
      askOut.textContent = "Thinking…";
      const q = $("askQ").value.trim() || DEFAULT_Q;
      try {
        const { truncated } = await sample(RULES + "\n\nQuestion: " + q + "\n\n" + fitContext(), {
          signal: ctl.signal,
          onText: ({ text }) => { askOut.textContent = text; },
        });
        if (truncated) askNote.textContent = "The answer was cut short. Ask a narrower question.";
      } catch (e) {
        const code = e && e.code;
        askOut.textContent = (e && e.text) || "";
        if (["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed"].includes(code)) {
          askBox.hidden = true;
          setStatus("Asking Claude is not available in this view.", "err");
        } else if (code !== "cancelled") {
          askNote.textContent = ASK_COPY[code] || "The answer was interrupted. Ask again.";
        }
      } finally {
        askBtn.disabled = false; stopBtn.hidden = true; ctl = null;
      }
    };
  });
})();
</script>
"""


def cut(text, start, end, what):
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    if i < 0 or j < 0:
        sys.exit(f"build_artifact: {what} not found in src/taskpane.html; update the build script.")
    return i, j


def build():
    src = SRC.read_text(encoding="utf-8")
    version = re.search(r'const APP_VERSION = "([^"]+)"', src).group(1)
    i, j = cut(src, "<body>", "</body>", "the page body")
    body = src[i + len("<body>"):j]
    # the Word task-pane header and mode switch become the page's top bar; the graph opens the stage
    a, b = cut(body, '<div id="modes"', "</div>", "the mode switch")
    modes = body[a:b + len("</div>")]
    a, _ = cut(body, "<header>", '<div id="preview"></div>', "the header")
    b = body.index('<div id="preview"></div>') + len('<div id="preview"></div>')
    body = body[:a] + TOP.replace("{version}", version).replace("{modes}", modes) + body[b:]
    # action bar: a Copy results button next to the file buttons
    old = '<button class="browser-only" id="btnSvg">Download SVG</button>'
    if old not in body:
        sys.exit("build_artifact: the SVG button not found; update the build script.")
    body = body.replace(old, '<button class="browser-only" id="btnSvg">Save SVG</button>\n  '
                             '<button id="btnCopyTop">Copy results</button>', 1)
    body = body.replace('<button class="browser-only" id="btnPng">Download PNG</button>',
                        '<button class="browser-only" id="btnPng">Save PNG</button>', 1)
    # the stage ends after the status line and the Ask Claude panel; the tabs become the side panel
    if '<div id="status"></div>' not in body:
        sys.exit("build_artifact: the status line not found; update the build script.")
    body = body.replace('<div id="status"></div>', '<div id="status" role="status"></div>\n' + ASK + '</div>\n<div class="panel">', 1)
    k = body.index("<script>")
    body = body[:k] + "</div>\n</main>\n" + body[k:]
    # drop the GitHub Pages self-update check (the page has no version.json next to it)
    a, b = cut(body, "(function checkForUpdate() {", "\n})();\n", "the self-update check")
    body = body[:a] + body[b + len("\n})();\n"):]
    page = HEAD + body.strip() + "\n" + EXTRA
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    return page, version


def check(page):
    """Load the page in headless Edge/Chrome (wrapped in the Artifact skeleton) and read the status line."""
    browsers = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium")] + [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    exe = next((p for p in browsers if p and Path(p).exists()), None)
    if not exe:
        sys.exit("--check needs Microsoft Edge or Google Chrome.")
    probe = ('<script>window.addEventListener("load", () => setTimeout(() => {'
             'const pre = document.createElement("pre"); pre.id = "probe";'
             'pre.textContent = JSON.stringify({status: document.getElementById("status").textContent,'
             'svg: !!document.querySelector("#preview svg"), example: !document.getElementById("exampleBadge").hidden,'
             'tabs: document.querySelectorAll("nav.tabs button").length});'
             'document.body.appendChild(pre); }, 300));</script>')
    doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
           'initial-scale=1,viewport-fit=cover"></head><body>' + page + probe + "</body></html>")
    tmp = Path(tempfile.mkdtemp(prefix="cdfit-artifact-"))
    try:
        f = tmp / "page.html"
        f.write_text(doc, encoding="utf-8")
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp / 'p'}",
               "--virtual-time-budget=15000", "--dump-dom", f.as_uri()]
        dom = subprocess.run(cmd, capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
    if not m:
        sys.exit("--check: the page did not finish loading.")
    result = html.unescape(m.group(1))
    print("check:", result)
    if "Tm = " not in result or '"svg":true' not in result or "Error" in result:
        sys.exit("--check failed: the example did not fit and plot.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="load the page headless and check that the example fits")
    a = ap.parse_args()
    page, version = build()
    print(f"{OUT} ({len(page.encode('utf-8')) // 1024} KB, add-in v{version})")
    if a.check:
        check(page)


if __name__ == "__main__":
    main()
