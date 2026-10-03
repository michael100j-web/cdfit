"""Runs every case in cases.json through the add-in itself (src/taskpane.html in headless Edge or Chrome)
and writes the add-in's results to golden.json, for test_parity.py.

Re-run after changing the add-in's fitting code:  py skill/tests/make_golden.py
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

RUNNER = """
<script>
(function () {
  const CASES = %s;
  const out = {};
  for (const [name, st] of Object.entries(CASES)) {
    try {
      applyState(JSON.parse(JSON.stringify(st)));
      const fit1 = (f) => f ? (f.error ? { error: f.error } : {
        p: f.p, se: f.se, ci: f.ci, ssr: f.ssr, df: f.df, n: f.n, r2: f.r2, syx: f.syx, iter: f.iter,
        converged: f.converged, ambiguous: f.ambiguous, step: f.step === undefined ? null : f.step,
        dir: f.dir === undefined ? null : f.dir, avoided: f.avoided || null, limit: !!f.limit }) : null;
      out[name] = {
        modelError: S.fit && !MODEL ? document.getElementById("eqMsg").textContent : null,
        params: MODEL ? MODEL.params : null,
        fits: DATA.series.map((s, j) => fit1(FITS[j])),
        bands: S.fit ? null : DATA.series.map(s => bands(s)),
        matrix: resultsMatrix(), summary: summaryText(), dataTable: dataTableText()
      };
    } catch (e) { out[name] = { exception: String((e && e.message) || e) }; }
  }
  out.__example = { melt: exampleData("melt"), uv: exampleData("uv"), spec: exampleData("spec") };
  out.__version = APP_VERSION;
  const pre = document.createElement("pre");
  pre.id = "golden";
  pre.textContent = JSON.stringify(out);
  document.body.appendChild(pre);
})();
</script>
"""


def browser():
    for p in [shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"]:
        if p and os.path.exists(p):
            return p
    sys.exit("Needs Microsoft Edge or Google Chrome.")


def main():
    page = (ROOT / "src" / "taskpane.html").read_text(encoding="utf-8")
    page = re.sub(r'<script src="https://appsforoffice[^"]*"></script>', "", page)   # browser mode, no network
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    page = page.replace("</body>", RUNNER % json.dumps(cases, ensure_ascii=False) + "</body>")
    tmp = Path(tempfile.mkdtemp(prefix="cdfit-golden-"))
    try:
        harness = tmp / "harness.html"
        harness.write_text(page, encoding="utf-8")
        cmd = [browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={tmp / 'profile'}", "--virtual-time-budget=60000", "--dump-dom", harness.as_uri()]
        dom = subprocess.run(cmd, capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m = re.search(r'<pre id="golden">(.*?)</pre>', dom, re.S)
    if not m:
        sys.exit("The add-in did not produce results:\n" + dom[-2000:])
    golden = json.loads(html.unescape(m.group(1)))
    (HERE / "golden.json").write_text(json.dumps(golden, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"golden.json: {len(golden) - 2} cases from add-in {golden['__version']}")


if __name__ == "__main__":
    main()
