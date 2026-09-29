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
| `tools/Sideload.ps1` | Adds the add-in to desktop Word for your user, or removes it |
| `server.js`, `package.json` | Optional local HTTPS server (needs Node.js) |

## Installing

Word loads add-ins only over **HTTPS**. There are two ways to set this up.

### Option A: host it once on GitHub Pages (recommended, no local server)

1. Create a GitHub repository called `cdfit` and push this folder to it.
2. Under the repository's **Settings → Pages**, choose "Deploy from branch" with `main` and `/ (root)`.
3. In this folder, run
   `.\tools\Set-AddinUrl.ps1 -BaseUrl https://<your-user>.github.io/cdfit/src`
4. Close Word, run `.\tools\Sideload.ps1`, then reopen Word. **CD Fit** now shows on the **Home** tab.

For Word on the web, go to **Home → Add-ins → More add-ins → My add-ins → Upload my add-in** and choose `manifest.hosted.xml`.

### Option B: run it locally (needs Node.js)

1. Run `winget install OpenJS.NodeJS.LTS` and open a new terminal.
2. `npm install`
3. `npm start`. This trusts a localhost development certificate (Windows asks you to confirm), starts the server
   and opens Word with the add-in loaded. `npm run stop` removes it again.

To preview in a browser without Word, run `npm run preview` (or `py -m http.server 3000 -d src`) and open http://localhost:3000/taskpane.html.

## Using it

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
