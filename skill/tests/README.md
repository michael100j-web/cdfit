# Tests for the CD Fit skill

All data here are synthetic. The repository is public, so never add measured data.

| file | what it does |
|---|---|
| `make_cases.py` | writes `cases.json`: 16 add-in states covering every branch of the fitter (direction constraint used or on its limit, fixed and hidden parameters, hidden and renamed columns, decimal commas, excluded ranges, equation and fit errors) |
| `make_golden.py` | runs those states through `src/taskpane.html` in headless Edge or Chrome and writes the add-in's own results to `golden.json` |
| `test_parity.py` | the Python port against `golden.json`: parameters to 0.1% of their standard error, standard errors to 1e-4, and the results table, summary, alt-text data table and example data character for character |
| `test_cli.py` | the command line, the Word round trip, .xlsx and JASCO input, error messages and the SKILL.md frontmatter |

```
py skill/tests/test_parity.py
py skill/tests/test_cli.py
```

After changing the add-in's fitting code: port the change to `skill/cdfit/scripts/cdfit_engine.py`, set
`ADDIN_VERSION`, run `py skill/tests/make_golden.py`, then the tests. Parameters are not bit-identical:
numpy's `exp`, `log` and `pow` round the last bit differently from V8, so on flat valleys the two fitters
can stop at points up to about 0.05% of a standard error apart, with the same sum of squares to 10 digits.
