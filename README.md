# CD Fit: a Word add-in for CD melting curves

This add-in works inside Word, a bit like Prism. You paste temperature and ellipticity data, it fits a model (by default the **Tm of CMPs**
trimer ⇌ 3 monomers equation), draws a Prism-style graph and puts the graph and a results table into your document.
The same fitting also runs inside Claude as a skill (see [Use CD Fit in Claude](#use-cd-fit-in-claude)).

## Files

| Path | Purpose |
|---|---|
| `src/taskpane.html` | The whole app: data table, equation engine, fitting, graph and Word integration. There is no build step. |
| `src/commands.html`, `src/assets/` | Ribbon support file and icons |
| `manifest.xml` | Office add-in manifest (points to `https://localhost:3000`) |
| `tools/Set-AddinUrl.ps1` | Makes `manifest.hosted.xml` for a hosted copy |
| `catalog/cdfit.xml` | Copy of `manifest.hosted.xml` that Word reads through a shared-folder catalog |
| `server.js`, `package.json` | Optional local HTTPS server (needs Node.js) |
| `skill/cdfit/` | The Claude skill: `SKILL.md` and a Python port of the fitting, graph and Word round trip |
| `skill/tests/` | Checks the port against the add-in itself (synthetic data only) |
| `tools/install_skill.py` | Installs the skill for Claude Code and builds `dist/cdfit-skill.zip` for claude.ai |
| `artifact/cdfit.html`, `artifact/src/`, `tools/build_artifact.py` | The add-in as a page in Claude (a claude.ai Artifact), built from `src/taskpane.html` plus the page's own parts |

## Use CD Fit in Claude

Give Claude a melting curve or a CD spectrum in a chat, pasted as columns or as a .txt, .csv, .xlsx or JASCO
file. It returns the Tm, the graph and the results table, with the add-in's numbers. Ask for a Word file and
the graph in it opens in the add-in for editing: click it with CD Fit open. Claude can also read and re-fit the
CD Fit graphs that are already in a Word document.

- **Claude Code** (desktop Code tab or CLI): run `py tools/install_skill.py`. It copies the skill to
  `~/.claude/skills/cdfit` and builds the zip below. New sessions pick it up.
- **claude.ai, for yourself**: upload `dist/cdfit-skill.zip` under **Customize → Skills → + → Create skill →
  Upload a skill**. Code execution must be on.
- **As a page in Claude**: `artifact/cdfit.html` is the add-in's own script in a full-page layout, published as a
  claude.ai Artifact. It adds Save PNG/SVG (the viewer asks before saving), an optional *Ask Claude about this
  fit*, which sends the data and results to Claude on the viewer's own usage, and, below the app, the 1st and
  2nd derivatives of the CD and UV fits in one figure (as fraction unfolded, with the peak temperatures in a
  table). Many files can be opened or dropped at once (one column each; JASCO exports keep the CD channel), and
  in CD spectrum mode an *All spectra at once* section lists every spectrum and plots θ at a chosen wavelength
  and Rpn against the temperature in the spectrum names, with the melting fit and Tm of each peptide. Its own
  code is in `artifact/src`. Rebuild it with
  `py tools/build_artifact.py --check` and republish it with the Artifact tool (icon `chart`, capabilities
  `downloads` and `sample`).
- **claude.ai, for the whole lab** (Team plan, Owner): upload the same zip under **Organization settings →
  Plugins & skills → Add → Upload a skill**. In that page's **Policy** tab, *Cloud code execution and file
  creation* and *Skills* must be on. The skill is then on for every member.

The skill is a Python port of the fitting code in `src/taskpane.html` (`skill/cdfit/scripts/cdfit_engine.py`).
`skill/tests/make_golden.py` runs 16 synthetic cases through the add-in itself in headless Edge or Chrome, and
`test_parity.py` requires the same parameters (to 0.1% of their standard errors), the same errors and
constraint flags, and the same results table, character for character. When the add-in's fitting code
changes, make the same change in `cdfit_engine.py`, set its `ADDIN_VERSION` to the new `APP_VERSION`, then run:

```
py skill/tests/make_golden.py
py skill/tests/test_parity.py
py skill/tests/test_cli.py
py tools/install_skill.py
py tools/build_artifact.py --check
```

## Installing

Word loads add-ins only over **HTTPS**. There are two ways to set this up.

### Option A: GitHub Pages plus a shared-folder catalog (recommended; this is what is set up)

The app is live at https://michael100j-web.github.io/cdfit/src/taskpane.html (repository `michael100j-web/cdfit`).
Word reads the add-in's manifest from a *trusted add-in catalog*. That has to be a network path, but your own C: drive works through `\\localhost\C$`.

One-time setup in desktop Word:
1. **File → Options → Trust Center → Trust Center Settings… → Trusted Add-in Catalogs**.
2. In *Catalog Url*, paste `\\localhost\C$\Users\micha\Documents\cdfit\catalog`, click **Add catalog**, tick **Show in Menu**, then click **OK** twice.
3. Close and reopen Word.
4. Go to **Home → Add-ins → More Add-ins → SHARED FOLDER**, choose **CD Fit** and click **Add**. The **CD Fit** button then shows on the **Home** tab.

If the URL changes, run `.\tools\Set-AddinUrl.ps1 -BaseUrl https://<your-user>.github.io/cdfit/src` and copy `manifest.hosted.xml` to `catalog\cdfit.xml`.
Pushing to `main` updates the live add-in within about a minute, and nothing needs to be reinstalled.
When you change the app, bump `APP_VERSION` in `src/taskpane.html` and `version` in `src/version.json` together. Word reloads the new version as soon as it sees the change, rather than waiting out GitHub's 10-minute cache.

(The per-user registry sideload, `WEF\Developer`, doesn't work on this Word build. Word only honours it while a debugger is attached.)

For Word on the web, go to **Home → Add-ins → More add-ins → My add-ins → Upload my add-in** and choose `manifest.hosted.xml`.

### Option B: run it locally (needs Node.js)

1. Run `winget install OpenJS.NodeJS.LTS` and open a new terminal.
2. `npm install`
3. `npm start`. This trusts a localhost development certificate (Windows asks you to confirm), starts the server
   and opens Word with the add-in loaded. `npm run stop` removes it again.

To preview in a browser without Word, run `npm run preview` (or `py -m http.server 3000 -d src`) and open http://localhost:3000/taskpane.html.

## Using it

The three buttons at the top switch modes. Each mode keeps its own data and settings, and a graph clicked in the document opens in the mode it was made in.
- **CD melting**: ellipticity vs temperature, fitted with the Tm model.
- **CD spectrum**: ellipticity vs wavelength, drawn as lines with a zero line and no fit. The Results tab gives λmax, λmin, the crossover and Rpn = θmax/|θmin|.
- **UV melting**: absorbance vs temperature, fitted with the same Tm model. By default the absorbance is constrained to rise on unfolding (see *Transition direction* below).

Fitting can be switched on or off in any mode (**Model → Fit a model to the data**).

1. **Data tab.** Paste columns from Excel: X in the first column, then one Y column per sample. A header row supplies the sample names.
   Decimal commas work. You can also select a table in Word and click **Import table from document**.
   Use *Multiply Y by* (e.g. 0.001) to convert to 10³ deg cm² dmol⁻¹, and *Exclude X outside* to leave points out of the fit (they still show, faded).
2. **Model tab.** Choose a preset or type your own equation in Prism syntax. Any name that is never defined becomes a parameter.
   Leave a starting value blank to have it estimated automatically, or tick **Fix** to hold that parameter constant.
3. **Graph tab.** Set axis ranges, ticks, titles (`*italic*`, `^{sup}`, `_{sub}`), symbol size, legend and export size.
4. **Results tab.** Shows the best-fit values, standard errors, 95% CIs, R² and Sy.x.
   **Insert results table** puts them into the document as a Word table.
5. **Insert graph** adds a 300/600 dpi PNG at the cursor. The data and all settings are stored in the picture's alt text.
   To change a graph later, click it, press **Edit selected graph**, make your changes, then press **Update selected graph**.

## Fitting details

- Levenberg–Marquardt least squares with numerical derivatives. This is the same approach Prism uses for nonlinear regression.
- Standard errors come from the covariance matrix scaled by SSR/df. The 95% CIs are ±t(0.975, df)·SE.
- The CMP preset reproduces your definition exactly: R = 8.31, H = −500 000 J/mol, and a strand concentration of 0.0002 M written into
  K and P. That concentration cancels out: P = e^(−a)/4 with a = H/(RT)·(T/Tm − 1), so the curve depends only on ΔH, and Tm is the
  midpoint at whatever concentration was measured. Editing it changes nothing. To fit H, delete the `H=` line and H becomes a fitted parameter.
- Automatic starting values: the native and unfolded baselines are fitted as lines against temperature in K over the first and last 20% of the points,
  and Tm is taken where the estimated folded fraction crosses 0.5.
- **Transition direction** (Model tab): holds the step at the midpoint, CDU − CDN evaluated at X = Tm, to one sign, and keeps Tm inside the fitted
  temperature range. Choose it when the baselines drift as much as the transition itself, so an unconstrained fit could settle on a feature of the
  drift, such as a falling step in UV data. The ordinary fit runs first. If its step has the wrong sign, or its Tm lies outside the data,
  Tm is scanned across the data, the other parameters are refitted at each Tm,
  and the best allowed fit is refined. The Results tab shows the step and, when the constraint changed the answer, the unconstrained Tm it replaced.
  It works with any equation that defines Tm, CDN and CDU. New UV melting sessions default to *rises on unfolding*, CD melting to *either direction*.
  Graphs saved before version 1.4 reopen with *either direction*, so their fits do not change.
