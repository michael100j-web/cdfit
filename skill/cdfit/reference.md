# CD Fit reference

## Equations (Prism syntax, as in the add-in's Model tab)

One definition per line, `NAME=expression`. `X` is the independent variable and the last line must define `Y`.
Any name that is never defined becomes a fitted parameter, in order of first use. Names are case-insensitive.
Lines starting with `;`, `//` or `#` are comments. Operators: `+ - * / ^` (also `**`) and parentheses.
Functions: `EXP LN LOG` (base 10) `LOG10 SQRT ABS CBRT MIN MAX SIN COS TAN ATAN POW`, constant `PI`.
Odd roots of negative numbers (e.g. `^(1/3)`) return the real root.

For the transition-direction constraint, an equation must define `Tm`, `CDN` and `CDU`. The step is
`CDU − CDN` evaluated at X = Tm.

### Presets

`cmp`: Tm of CMPs (trimer ⇌ 3 monomers, ΔH fixed), the default:

```
R=8.31
H=-500000
K=EXP(H/(R*(X+273.15))*((X+273.15)/(Tm+273.15)-1)-ln(0.75*0.0002^2))
P=1/(3*K*(0.0002^2))
U=(-P/2+(P^2/4+P^3/27)^(1/2))^(1/3)
V=-(P/2+(P^2/4+P^3/27)^(1/2))^(1/3)
F= U+V+1
CDU=REFU+DEU*(X+273.15)
CDN=REFN+DEN*(X+273.15)
Y=F*(CDN-CDU)+CDU
```

F is the folded fraction from the cubic (Cardano). With K as written, P = e^(−a)/4 with
a = H/(R·T)·(T/Tm − 1), so the 0.0002 cancels: the curve shape depends only on ΔH, and Tm is the midpoint at
the measured concentration. `--fit-dH` deletes the `H=` line (H then starts at −300000 J/mol), and
`--dH VALUE` rewrites it.

`twostate`: a monomolecular two-state transition with ΔH fitted, `K=EXP(-H/R*(1/T-1/(Tm+273.15)))`,
`F=K/(1+K)`, and the same baselines.

`boltz`: Boltzmann sigmoid `Y=Bottom+(Top-Bottom)/(1+EXP((V50-X)/Slope))`.

## Fitting (identical to the add-in)

- Starting values: native and unfolded baselines fitted as lines against T in K over the first and last 20%
  of the points (at least 3), and Tm where the estimated folded fraction crosses 0.5. Bottom/Top are the means
  of those points, V50 = Tm, Slope = X range / 15, H = −300000. Any other parameter starts at 1.
- Levenberg–Marquardt with forward-difference derivatives, up to 400 iterations. Standard errors come from
  the central-difference covariance scaled by SSR/df, and 95% CI = ±t(0.975, df)·SE.
- Direction constraint: the ordinary fit runs first. If its step has the wrong sign or its Tm is outside the
  data, Tm is scanned over 25 points across the data (the other parameters refitted at each), and the best
  allowed point is refined. If that refinement leaves the allowed region, Tm is settled by a finer scan and
  has no standard error (`on_constraint`).

## Outputs of `fit`

For each graph, in the output folder:

| file | contents |
|---|---|
| `<name>.png` (`.svg`, `.pdf`) | the graph, `exportCm` wide (12 cm) at 300 or 600 dpi |
| `<name>_results.tsv` | the add-in's results table (Copy results / Insert results table), UTF-8 for Excel |
| `<name>_results.json` | everything below, machine-readable |
| `<name>_state.json` | the add-in's state for this graph; `fit` accepts it as input |
| `<name>.docx` (with `--docx`) | the graph(s) and results table(s); graphs editable in the add-in |

`_results.json` has `mode`, `model`, `equation`, `direction`, `model_error`, `summary`, `table`, `notes`
(per data set) and `series`. Each series has `name`, `column`, `points`, `excluded` and a `status`:
`fitted`, `error`, `hidden`, `no points` or `plotted` (spectra). Fitted series also have `params`
(`value`, `se`, `ci95`, `fixed` and a formatted `text` for each parameter), `Tm`, `r2`, `syx`, `n`, `df`,
`converged`, `iterations`, `ambiguous`, `step`, `direction`, plus `unconstrained` (the fit the constraint
replaced) and `on_constraint` when they apply. Spectra have `bands`: `xMax`, `yMax`, `xMin`, `yMin`,
`cross`, `rpn`, `hasPos`, `n`. `null` means not available (NaN).

`--json` prints the same record to stdout (a list when a .docx gave several graphs).

## Word round trip

A graph picture made by CD Fit (the add-in or this skill) has the title `CD Fit graph #<id>` and alt text in
three parts: a summary line, the plotted data as semicolon-separated text (readable without the add-in), and
`#CDFIT-STATE ` followed by the state JSON. The add-in reads that JSON when the picture is clicked. It also
keeps a backup copy in the document's add-in settings (`cdfit:<id>`), which `read_graphs` falls back on.

State JSON fields (the add-in's `S`): `mode` (`melt`, `spec`, `uv`), `dataText` (the pasted table), `yMult`,
`xFrom`, `xTo`, `series` (per column: `color`, `visible`, `name`, and optional `shape`, `fill`, `size`,
`line`), `preset`, `eqText`, `params` (lower-case name → `{value, fixed}`), `fit`, `stepDir` (`any`, `up`,
`down`) and `fmt` (graph settings: `xTitle`, `yTitle`, `xMin`, `xMax`, `xStep`, `xMinor`, `xScale`, the
same for y, `plotW`, `plotH`, `fontSize`, `fontFamily`, `markerSize`, `lineW`, `axisW`, `legend`,
`showPoints`, `showCurve`, `connect`, `zeroLine`, `curveAxis`, `legendTm`, `tmLine`, `hollow`, `exportCm`,
`exportFmt`). Graphs saved before add-in 1.4 have no `stepDir` and open with `any`.

Symbols for `series[].shape`: circle, square, triangle, tridown, diamond, cross, plus, none.
Curve styles for `series[].line`: solid, dash, dot, dashdot, none.
