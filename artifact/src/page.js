"use strict";
/* Page additions around the add-in's script: files saved through the viewer, Ask Claude, the example-data note.
   CDFIT_AFTER_REFRESH and cdfitFiles are shared with derivatives.js, which runs after this script. */
const CDFIT_AFTER_REFRESH = [];
const cdfitFiles = {
  save: null,   // set once the viewer can save files
  pngBlob(svg, w, h) {
    const dpi = S.fmt.exportFmt === "png600" ? 600 : 300, cm = +S.fmt.exportCm || 12, scale = (cm / 2.54 * dpi) / w;
    return new Promise((resolve, reject) => {
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
  },
  stem() {
    const names = (DATA ? DATA.series : []).filter((s) => S.series[s.idx] && S.series[s.idx].visible).map((s) => s.name);
    const base = { melt: "CD melt", spec: "CD spectrum", uv: "UV melt" }[S.mode] || "CD Fit";
    return (base + (names.length ? " - " + names.slice(0, 3).join(", ") : "")).replace(/[\\/:*?"<>|]+/g, "").slice(0, 80);
  },
};

// A name shown literally in graph markup (*italic*, ^{sup}, _{sub})
const cdfitMarkupEscape = (s) => String(s).replace(/[\\*^_{}]/g, (c) => "\\" + c);

// Fit a state that is not on screen with the add-in's own functions, then put the live page state back.
// Results are kept per state, so typing refits only once.
const cdfitFitState = (function () {
  const fitted = new Map();
  const keyOf = (st) => JSON.stringify([st.mode, st.dataText, st.eqText, st.params, st.xFrom, st.xTo, st.yMult,
    st.stepDir, st.fit, (st.series || []).map((c) => c && [c.visible, c.name, c.color])]);
  return function (st) {
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
    if (fitted.size > 8) fitted.delete(fitted.keys().next().value);
    return out;
  };
})();

(function () {
  const cl = window.claude && typeof window.claude.use === "function" ? window.claude : null;
  const use = (name) => (cl ? cl.use(name).catch(() => null) : Promise.resolve(null));

  // Note while the example data is loaded; other page parts redraw after every refresh
  const examples = {};
  const badge = $("exampleBadge");
  const markExample = () => {
    if (!(S.mode in examples)) examples[S.mode] = exampleData(S.mode).trim();
    badge.hidden = (S.dataText || "").trim() !== examples[S.mode];
  };
  const baseRefresh = refresh;
  refresh = function (refit) {
    baseRefresh(refit);
    markExample();
    for (const f of CDFIT_AFTER_REFRESH) { try { f(); } catch (e) { console.warn(e); } }
  };
  markExample();

  $("btnCopyTop").onclick = () => $("btnCopy").click();

  // PNG and SVG, saved through the viewer, which asks the viewer to confirm each file
  const saveButtons = () => document.querySelectorAll(".needs-downloads");
  use("downloads").then((downloads) => {
    if (!downloads) return;
    saveButtons().forEach((b) => { b.hidden = false; });
    const gone = ["unavailable", "not_granted", "capability_disabled", "capability_removed"];
    cdfitFiles.save = async (filename, data) => {
      try {
        await downloads.save({ filename, data });
        setStatus("Saved " + filename + ".", "ok");
      } catch (e) {
        const code = e && e.code;
        if (code === "declined") return;
        if (gone.includes(code)) {
          saveButtons().forEach((b) => { b.hidden = true; });
          setStatus("Saving files is not available in this view.", "err");
          return;
        }
        setStatus(code === "rate_limited" ? "Another save is waiting for your answer." : "The file could not be saved.", "err");
      }
    };
    $("btnPng").onclick = async () => {
      if (!DATA || !DATA.series.length) { setStatus("Add data first.", "err"); return; }
      const { svg, width, height } = renderSVG();
      try { await cdfitFiles.save(cdfitFiles.stem() + ".png", await cdfitFiles.pngBlob(svg, width, height)); }
      catch (e) { setStatus(e.message, "err"); }
    };
    $("btnSvg").onclick = () => {
      if (!DATA || !DATA.series.length) { setStatus("Add data first.", "err"); return; }
      cdfitFiles.save(cdfitFiles.stem() + ".svg", renderSVG().svg);
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
    if (typeof cdfitDerivatives !== "undefined") {
      const d = cdfitDerivatives.summary();
      if (d) out.push("Derivatives of the CD and UV fits, as fraction unfolded alpha (°C; the peak of d(alpha)/dT is where d2(alpha)/dT2 crosses zero; dY/dT is the raw fitted signal):\n" + d);
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
