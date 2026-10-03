"""Build artifact/cdfit.html, CD Fit as a page inside Claude (a claude.ai Artifact), from src/taskpane.html.

The page runs the add-in's own script unchanged: the same parser, fitter, graph and results. This script swaps the
add-in's Word task-pane shell for a full-page layout with light and dark themes, and adds the page's own parts from
artifact/src: saving the graph through the viewer (`downloads`), an optional "Ask Claude about this fit" panel
(`sample`), and a section below the app with the 1st and 2nd derivatives of the CD and UV fits.

  py tools/build_artifact.py            write artifact/cdfit.html
  py tools/build_artifact.py --check    also load it in headless Edge/Chrome and check that the examples fit

Publish with the Artifact tool: icon "chart", capabilities {"downloads": true, "sample": {}}.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "taskpane.html"
PARTS = ROOT / "artifact" / "src"
OUT = ROOT / "artifact" / "cdfit.html"

HEAD = """<title>CD Fit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
{css}</style>
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

DERIV = """<section class="section" id="derivatives" aria-labelledby="derivTitle">
  <div class="section-head">
    <h2 id="derivTitle">1st and 2nd derivatives of the CD and UV fits</h2>
    <div class="actions"><button class="needs-downloads" id="derivPng" hidden>Save PNG</button><button class="needs-downloads" id="derivSvg" hidden>Save SVG</button></div>
  </div>
  <div class="section-body">
    <figure class="paper"><div id="derivSvgBox"></div></figure>
    <div class="section-side">
      <div id="derivTable"></div>
      <p class="hint" id="derivNote"></p>
      <p class="hint">α = (Y − native baseline) / (unfolded − native baseline), from each fit. Solid lines and filled points are CD, dashed lines and open points UV. Dotted lines mark the peak of dα/dT, where d²α/dT² crosses zero; the maximum and minimum of d²α/dT² mark where the transition starts and ends. dY/dT is the derivative of the fitted signal itself, baselines included.</p>
      <p class="hint">With the CMP model (ΔH −500 kJ/mol) the peak of dα/dT lies about 1.5–2 °C above T<sub>m</sub> (α = ½), so say which one you quote.</p>
    </div>
  </div>
</section>
"""

SPECTRA = """<section class="section" id="spectra" aria-labelledby="specTitle" hidden>
  <div class="section-head">
    <h2 id="specTitle">All spectra at once</h2>
    <div class="actions">
      <button id="specGradient">Colour by temperature</button>
      <button id="specCopy">Copy table</button>
      <button class="needs-downloads" id="specPng" hidden>Save PNG</button>
      <button class="needs-downloads" id="specSvg" hidden>Save SVG</button>
    </div>
  </div>
  <div class="section-body">
    <figure class="paper" id="specFigure"><div id="specSvgBox"></div></figure>
    <div class="section-side">
      <label class="f" for="specLambda">Wavelength for θ against temperature (nm)<input type="number" id="specLambda" step="any" value="225"></label>
      <p id="specFit"></p>
      <p class="hint" id="specNote"></p>
      <div class="row" id="specMeltRow" hidden><button class="primary" id="specToMelt">Fit θ against temperature in CD melting</button></div>
      <div class="row" id="specConfirm" hidden><span class="hint">This replaces your data under CD melting.</span><button class="primary" id="specYes">Replace and fit</button><button id="specNo">Cancel</button></div>
      <p class="hint">Each row is one spectrum. A temperature in the name (“CMP-1 20 °C”, or a file called “CMP1_20C”) puts the spectra on a temperature axis, one line per peptide.</p>
    </div>
  </div>
  <div id="specTable"></div>
</section>
"""


def cut(text, start, end, what):
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    if i < 0 or j < 0:
        sys.exit(f"build_artifact: {what} not found in src/taskpane.html; update the build script.")
    return i, j


def swap(text, old, new, what):
    if old not in text:
        sys.exit(f"build_artifact: {what} not found in src/taskpane.html; update the build script.")
    return text.replace(old, new, 1)


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
    # action bar: files saved through the viewer, Copy results, and a link down to the derivatives
    body = swap(body, '<button class="browser-only" id="btnPng">Download PNG</button>',
                '<button class="browser-only needs-downloads" id="btnPng" hidden>Save PNG</button>', "the PNG button")
    body = swap(body, '<button class="browser-only" id="btnSvg">Download SVG</button>',
                '<button class="browser-only needs-downloads" id="btnSvg" hidden>Save SVG</button>\n  '
                '<button id="btnCopyTop">Copy results</button>\n  '
                '<a class="jump" href="#derivatives">1st and 2nd derivatives ↓</a>', "the SVG button")
    # the stage ends after the status line and the Ask Claude panel; the tabs become the side panel
    body = swap(body, '<div id="status"></div>',
                '<div id="status" role="status"></div>\n' + ASK + '</div>\n<div class="panel">', "the status line")
    k = body.index("<script>")
    body = body[:k] + "</div>\n</main>\n" + DERIV + SPECTRA + body[k:]
    # drop the GitHub Pages self-update check (the page has no version.json next to it)
    a, b = cut(body, "(function checkForUpdate() {", "\n})();\n", "the self-update check")
    body = body[:a] + body[b + len("\n})();\n"):]
    css = (PARTS / "page.css").read_text(encoding="utf-8")
    scripts = "".join(f"<script>\n{(PARTS / name).read_text(encoding='utf-8')}</script>\n"
                      for name in ("page.js", "panels.js", "import.js", "derivatives.js", "spectra.js"))
    page = HEAD.replace("{css}", css) + body.strip() + "\n" + scripts
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    return page, version


def check(page):
    """Load the page in headless Edge/Chrome (wrapped in the Artifact skeleton) and read what it shows."""
    browsers = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium")] + [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    exe = next((p for p in browsers if p and Path(p).exists()), None)
    if not exe:
        sys.exit("--check needs Microsoft Edge or Google Chrome.")
    probe = r"""<script>
window.addEventListener("error", (e) => { window.__err = String(e.message); });
window.addEventListener("load", () => setTimeout(async () => {
  const q = (s) => document.querySelector(s), rows = (s) => [...document.querySelectorAll(s + " tbody tr")];
  const out = { status: q("#status").textContent, svg: !!q("#preview svg"), example: !q("#exampleBadge").hidden,
    tabs: document.querySelectorAll("nav.tabs button").length, deriv: !!q("#derivSvgBox svg"),
    derivRows: rows("#derivTable").map((r) => [...r.cells].map((c) => c.textContent.trim()).join(" | ")) };
  try {
    switchMode("spec");
    const g = (x, c, w) => Math.exp(-(((x - c) / w) ** 2));
    const jascoFile = (f) => {
      const lines = ["TITLE\tCMP1", "XUNITS\tNANOMETERS", "YUNITS\tCD [mdeg]", "Y2UNITS\tHT [V]", "XYDATA"];
      for (let x = 260; x >= 190; x -= 1) lines.push(x + "\t" + (f * 4.3 * g(x, 225, 7.5) - 39 * g(x, 197.5, 6.5)).toFixed(4) + "\t" + (300 + x).toFixed(1));
      return lines.concat(["", "##### Extended Information", "[Comments]"]).join("\n");
    };
    await cdfitImport.load([20, 40, 60].map((t, k) => new File([jascoFile(1 - k * 0.4)], "CMP1_" + t + "C.txt")));
    out.imported = { names: DATA.series.map((s) => s.name), points: DATA.series.map((s) => s.xs.length) };
    const temps = [4, 10, 20, 30, 35, 40, 45, 50, 60, 70, 80], frac = (t, tm) => 1 / (1 + Math.exp((t - tm) / 3));
    const lines = [["λ (nm)"].concat(temps.map((t) => "CMP-1 " + t + " °C"), temps.map((t) => "CMP-2 " + t + " °C")).join("\t")];
    for (let x = 190; x <= 260; x += 1)
      lines.push([x].concat(temps.map((t) => frac(t, 42) * 4.3 * g(x, 225, 7.5) - 39 * g(x, 197.5, 6.5)),
                            temps.map((t) => frac(t, 33) * 4.3 * g(x, 225, 7.5) - 39 * g(x, 197.5, 6.5))).join("\t"));
    S.dataText = lines.join("\n"); S.series = []; refresh(true);
    q("#specGradient").click();
    out.spectra = { fit: q("#specFit").textContent, visible: !q("#spectra").hidden, rows: rows("#specTable").length, figure: !!q("#specSvgBox svg"),
      first: q("#spectra").nextElementSibling === q("#derivatives"), colours: new Set(S.series.map((s) => s.color)).size };
    q("#specToMelt").click();
    out.melt = { mode: S.mode, status: q("#status").textContent, series: DATA.series.map((s) => s.name), spectraHidden: q("#spectra").hidden };
  } catch (e) { out.flowError = String((e && e.message) || e); }
  out.error = window.__err || null;
  const pre = document.createElement("pre"); pre.id = "probe"; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
}, 300));
</script>"""
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
    r = json.loads(result)
    ok = (r.get("error") is None and not r.get("flowError") and r["svg"] and r["deriv"] and "Tm = " in r["status"]
          and r["imported"]["names"] == ["CMP1_20C", "CMP1_40C", "CMP1_60C"]
          and r["spectra"]["visible"] and r["spectra"]["rows"] == 22 and r["spectra"]["figure"] and r["spectra"]["first"]
          and r["spectra"]["colours"] == 22 and r["spectra"]["fit"].count("Tm = ") == 2 and r["melt"]["mode"] == "melt" and "Tm = " in r["melt"]["status"]
          and r["melt"]["series"] == ["CMP-1", "CMP-2"] and r["melt"]["spectraHidden"])
    if not ok:
        sys.exit("--check failed: see the values above.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="load the page headless and check that the examples fit")
    a = ap.parse_args()
    page, version = build()
    print(f"{OUT} ({len(page.encode('utf-8')) // 1024} KB, add-in v{version})")
    if a.check:
        check(page)


if __name__ == "__main__":
    main()
