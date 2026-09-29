# CD Fit: a Word add-in for CD melting curves

This add-in works inside Word, a bit like Prism. You paste temperature and ellipticity data, it fits a model (by default the **Tm of CMPs**
trimer ⇌ 3 monomers equation), draws a Prism-style graph and puts the graph and a results table into your document.

## Files

| Path | Purpose |
|---|---|
| `src/taskpane.html` | The whole app: data table, equation engine, fitting, graph and Word integration. There is no build step. |
| `src/commands.html`, `src/assets/` | Ribbon support file and icons |
| `manifest.xml` | Office add-in manifest (points to `https://localhost:3000`) |
| `tools/Set-AddinUrl.ps1` | Makes `manifest.hosted.xml` for a hosted copy |
| `catalog/cdfit.xml` | Copy of `manifest.hosted.xml` that Word reads through a shared-folder catalog |
| `server.js`, `package.json` | Optional local HTTPS server (needs Node.js) |

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
  K and P. To use a different concentration, or to fit H, edit those lines. For example, delete the `H=` line and H becomes a fitted parameter.
- Automatic starting values: the native and unfolded baselines are fitted as lines against temperature in K over the first and last 20% of the points,
  and Tm is taken where the estimated folded fraction crosses 0.5.
- **Transition direction** (Model tab): holds the step at the midpoint, CDU − CDN evaluated at X = Tm, to one sign, and keeps Tm inside the fitted
  temperature range. Choose it when the baselines drift as much as the transition itself, so an unconstrained fit could settle on a feature of the
  drift, such as a falling step in UV data. The ordinary fit runs first. If its step has the wrong sign, or its Tm lies outside the data,
  Tm is scanned across the data, the other parameters are refitted at each Tm,
  and the best allowed fit is refined. The Results tab shows the step and, when the constraint changed the answer, the unconstrained Tm it replaced.
  It works with any equation that defines Tm, CDN and CDU. New UV melting sessions default to *rises on unfolding*, CD melting to *either direction*.
  Graphs saved before version 1.4 reopen with *either direction*, so their fits do not change.
