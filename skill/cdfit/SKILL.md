---
name: cdfit
description: Fits CD and UV melting curves of collagen model peptides (Tm from the trimer ⇌ 3 monomers model) and analyses CD spectra (λmax, λmin, crossover, Rpn) exactly as the CD Fit Word add-in does, with the same model, fitter, defaults and Prism-style graph. Use whenever someone shares melting data (temperature vs ellipticity or absorbance, including Chirascan or JASCO exports with several wavelengths) or a CD spectrum and wants a Tm, a fit, a graph or a results table ("fit this melt", "what's the Tm", "make a CD Fit graph"), or brings a Word document with CD Fit graphs to read, re-fit or restyle. Writes PNG/SVG/PDF graphs, results tables, and Word files whose graphs stay editable in the CD Fit add-in.
---

# CD Fit

`scripts/cdfit.py` is the CD Fit Word add-in (github.com/michael100j-web/cdfit) as a command-line tool: a
line-by-line port of its data parser, equation compiler, starting values, Levenberg–Marquardt fit,
transition-direction constraint, number formatting and graph. Its numbers match the add-in's (the repository
tests this against the add-in itself), so a Tm from here and a Tm from Word agree. Never fit melting data some
other way when this skill applies, and never compute or round values by hand: report what the script prints.

## Run it

Needs Python 3 with numpy and matplotlib (openpyxl for .xlsx). Use `py` on Windows, `python3` elsewhere.
`SKILL_DIR` below is this skill's folder.

1. Get the data into a file as given: X in the first column, one Y column per sample, an optional header row
   with the names. Tabs, semicolons, commas or spaces all work, and decimal commas are fine. .txt, .csv, .tsv,
   .dat, .xlsx, JASCO exports and Chirascan (Pro-Data) CSV exports can be passed directly, as they are. If the
   data were pasted into the chat, write them to a .txt file unchanged (no rounding, no reordering).
2. Fit:
   ```
   py SKILL_DIR/scripts/cdfit.py fit data.txt --mode melt
   ```
   Add `--docx` for a Word file with the graph and results table. Outputs go to `<data>_cdfit/` next to the
   data unless `--out DIR` is given (on claude.ai, use `--out /mnt/user-data/outputs`).
3. Read the printed summary (a `read:` line when the files needed reading, one line per sample, then any
   `note:` lines) and show the user the PNG.

## Spectrometer files

- **Chirascan** CSV (starts with `ProDataCSV`): the script takes the CircularDichroism block (the Absorbance block
  with `--mode uv`) and ignores HV, Voltage, Count, SE and Temperature. A melting scan recorded at one or more
  wavelengths gives the signal at `--wavelength` (default 225 nm) against temperature. A spectrum file is read as a
  spectrum, named with the temperature in its remarks. Curves are named after the files.
- **JASCO** exports: the CD channel; an export of spectra at several temperatures is read as one spectrum per
  temperature.
- **Spectra named with their temperatures** (several files, or one table with a column per temperature) give θ at
  `--wavelength` against temperature, one curve per peptide, when the mode is `melt`.
- A wavelength that was not measured is taken between two measured ones only when they are at most 5 nm apart.
  Otherwise the script stops and lists what was measured (for example 205–285 nm every 20 nm).
- Without `--mode`, the files choose it: spectra are read in spectrum mode and melting scans in melting mode. With
  `--mode`, files that do not fit it are skipped, or the script stops and says which mode to use.

## Modes and defaults (the add-in's)

| `--mode` | data | fit | transition direction |
|---|---|---|---|
| `melt` (default) | T (°C) vs ellipticity | CMP model | either |
| `uv` | T (°C) vs absorbance | CMP model | rises on unfolding |
| `spec` | λ (nm) vs [θ] | none: λmax, λmin, crossover, Rpn | – |

CMP model: trimer ⇌ 3 monomers with ΔH fixed at −500 kJ/mol and sloping native/unfolded baselines (linear in
K). Fitted parameters: Tm, REFU and DEU (unfolded baseline), REFN and DEN (native baseline). The strand
concentration written in the equation cancels out of the curve, so no concentration is needed. Tm is the
midpoint at whatever concentration was measured.

## Options worth knowing

- `--direction up|down|any`: hold the step at Tm (unfolded − native baseline) to one sign and Tm inside the data.
  Use `down` for CD at ~225 nm, `up` for UV hyperchromicity, when baseline drift is as big as the transition.
- `--xrange MIN MAX`: fit only that X range. Points outside are still drawn, faded.
- `--fit-dH` fits ΔH instead of fixing it; `--dH=-400000` fixes another value (J/mol; keep the `=`). The
  fixed −500 kJ/mol is the lab's convention, so keep it unless asked. If ΔH is fitted, say so next to the Tm.
- `--ymult 0.001` scales Y, e.g. to 10³ deg cm² dmol⁻¹. `--columns 1,3` fits only those Y columns and
  `--names "A|B"` renames them.
- `--start Tm=40`, `--fix DEN=0`, `--free Tm`: starting values and fixed parameters (names as in the equation).
- `--preset twostate` (monomolecular, ΔH fitted) or `--preset boltz`; `--equation FILE` for a Prism-syntax
  equation (see reference.md).
- Graph: `--xtitle`, `--ytitle` (markup `*italic*`, `^{sup}`, `_{sub}`), `--legend tr|tl|br|bl|off`,
  `--width-cm 12`, `--dpi 600`, `--formats png,svg,pdf`, `--set KEY=VALUE` for any other add-in setting.
- `--wavelength 222`: the wavelength taken from scans and spectra (default 225 nm, the CMP maximum; use the
  peptide's own maximum if it differs).
- Several files at once: `fit a.csv b.csv c.csv` makes one table, one column per file, matched by X and sorted
  naturally (4 °C before 20 °C), so several Chirascan melts give one graph with one Tm each. In
  spectrum mode the script also writes `<name>_spectra.tsv` (one row per spectrum: λmax, λmin, crossover, Rpn and
  the value at `--wavelength`, default 225 nm). When the spectrum names carry temperatures ("CMP-1 20 °C",
  "CMP1_20C"), it also writes `<name>_melt_225nm.txt` (θ at that wavelength against temperature, one column per
  peptide), fits it with the CMP model and prints the Tm from the spectra, with its graph in `<name>_melt_225nm.png`.
- Word documents: `fit report.docx` re-fits every CD Fit graph in the file (each picture carries its data and
  settings in its alt text). `list report.docx` lists them and `--graph 2` picks one. Combine with options to
  re-fit or restyle, and with `--docx` to get the new graphs back as a Word file.

## Reporting

- Per sample: Tm ± standard error in °C, the 95% CI, R² and N, as printed. Name the model ("CMP model, ΔH
  fixed at −500 kJ/mol") and the direction if constrained.
- Say what was read when there is a `read:` line (e.g. "CD at 225 nm from the Chirascan scan"), and pass on
  anything it skipped.
- Pass on every `note:` line. They mean the Tm needs care: the constraint changed the answer, Tm sits on the
  constraint with no standard error, the fit did not converge, or the parameters are not identifiable. A curve
  with no transition in the measured range (a straight line) has no Tm: say so rather than quoting the number.
- If a fit fails, give the message and the likely fix (a direction, an X range, or a start value).
- Show the graph and mention any Word file. Its graph can be edited in Word: open CD Fit (Home tab), click the
  picture, change things, then press **Update selected graph**.
- Keep the reply short: numbers first, little prose.

## Science notes for CMPs

- A trimer's Tm depends on concentration, and a scanned melt's Tm also depends on scan rate (heating scans read
  high). Compare Tm values only at the same concentration and scan rate, or say that they differ.
- For a spectrum, an Rpn of about 0.1 or more with a positive band near 225 nm is typical of a collagen
  triple helix.

## Files

- `scripts/cdfit.py`: the command line (`fit`, `list`, `example`); `fit -h` lists every option.
- `scripts/cdfit_engine.py`: the port of the add-in's parser, model compiler, fitter and formatting.
- `scripts/cdfit_plot.py`: the add-in's graph layout drawn with matplotlib.
- `scripts/cdfit_word.py`: Word files with add-in-editable graphs, and reading CD Fit graphs from .docx.
- `scripts/cdfit_files.py`: reading Chirascan, JASCO and other files, and taking one wavelength from a scan (the
  same rules as the CD Fit page in Claude).
- `scripts/cdfit_spectra.py`: many spectra at once (a row each, θ at a wavelength against temperature).
- `reference.md`: equation syntax, the presets, output files, the results JSON and the saved-state format.
