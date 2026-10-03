"""The Python port must give the add-in's results: every case in cases.json against golden.json,
which make_golden.py made by running the same states through src/taskpane.html.

Run:  py skill/tests/test_parity.py      (or python -m pytest skill/tests)
"""
import json
import math
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cdfit", "scripts"))
import cdfit_engine as E  # noqa: E402

CASES = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
GOLDEN = json.load(open(os.path.join(HERE, "golden.json"), encoding="utf-8"))


def num(v):
    return math.nan if v is None else v


class Parity(unittest.TestCase):
    def close(self, a, b, rel, what, abs_tol=0.0):
        a, b = num(a), num(b)
        if math.isnan(a) or math.isnan(b) or math.isinf(a) or math.isinf(b):
            self.assertEqual(math.isnan(a), math.isnan(b), what)
            if not math.isnan(a):
                self.assertEqual(a, b, what)
            return
        self.assertTrue(math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol), f"{what}: python {a!r} vs add-in {b!r}")

    def check_fit(self, name, j, f, g):
        where = f"{name} series {j}"
        if g is None:
            self.assertIsNone(f, where)
            return
        if "error" in g:
            self.assertEqual(f.get("error"), g["error"], where)
            return
        self.assertNotIn("error", f, f"{where}: {f.get('error')}")
        # The fits stop at the same minimum but, on flat valleys, at points that differ by rounding noise
        # (numpy's exp/log/pow are not bit-identical to V8's), so parameters must agree to 0.1% of their
        # standard error; the formatted results below must match exactly.
        scale = max([abs(v) for v in g["p"]] + [1e-300])
        tol = [max(1e-9 * scale, 1e-3 * num(se) if num(se) == num(se) else 0) for se in g["se"]]
        for i, (a, b) in enumerate(zip(f["p"], g["p"])):
            self.close(a, b, 1e-6, f"{where} p[{i}]", abs_tol=tol[i])
        for i, (a, b) in enumerate(zip(f["se"], g["se"])):
            self.close(a, b, 1e-4, f"{where} se[{i}]")
        for i, (a, b) in enumerate(zip(f["ci"], g["ci"])):
            self.assertEqual(a is None, b is None, f"{where} ci[{i}]")
            if a is not None:
                self.close(a[0], b[0], 1e-6, f"{where} ci[{i}] low", abs_tol=10 * tol[i])
                self.close(a[1], b[1], 1e-6, f"{where} ci[{i}] high", abs_tol=10 * tol[i])
        self.close(f["ssr"], g["ssr"], 1e-8, f"{where} ssr")
        self.close(f["syx"], g["syx"], 1e-6, f"{where} syx")
        self.close(f["r2"], g["r2"], 0, f"{where} r2", abs_tol=1e-9)
        for k in ("df", "n", "converged", "ambiguous"):
            self.assertEqual(f[k], g[k], f"{where} {k}")
        self.assertEqual(f.get("dir"), g["dir"], f"{where} dir")
        self.assertEqual(bool(f.get("limit")), g["limit"], f"{where} limit")
        if g["step"] is not None:
            self.close(f.get("step"), g["step"], 1e-5, f"{where} step", abs_tol=1e-9)
        self.assertEqual(bool(f.get("avoided")), bool(g["avoided"]), f"{where} avoided")
        if g["avoided"]:
            self.close(f["avoided"]["tm"], g["avoided"]["tm"], 1e-5, f"{where} avoided tm")
            self.assertEqual(f["avoided"]["outside"], g["avoided"]["outside"], f"{where} avoided outside")

    def test_cases(self):
        self.assertEqual(GOLDEN["__version"], E.ADDIN_VERSION, "golden.json comes from another add-in version")
        for name, st in CASES.items():
            with self.subTest(case=name):
                g = GOLDEN[name]
                self.assertNotIn("exception", g)
                s = E.Session(st)
                self.assertEqual(s.model_error, g["modelError"])
                self.assertEqual(s.model.params if s.model else None, g["params"])
                fits = [s.fits[j] if j < len(s.fits) else None for j in range(len(s.data["series"]))]
                self.assertEqual(len(fits), len(g["fits"]))
                for j, (f, gf) in enumerate(zip(fits, g["fits"])):
                    self.check_fit(name, j, f, gf)
                if g["bands"] is not None:
                    for ser, gb in zip(s.data["series"], g["bands"]):
                        b = E.bands(ser)
                        for k, v in gb.items():
                            if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                                self.close(b[k], v, 1e-12, f"{name} bands {k}")
                            else:
                                self.assertEqual(b[k], v, f"{name} bands {k}")
                self.assertEqual(s.results_matrix(), g["matrix"])
                self.assertEqual(s.summary_text(), g["summary"])
                self.assertEqual(s.data_table_text(), g["dataTable"])

    def test_same_version_as_the_add_in(self):
        page = os.path.join(HERE, "..", "..", "src", "taskpane.html")
        if not os.path.exists(page):
            self.skipTest("add-in source not here")
        with open(page, encoding="utf-8") as fh:
            m = re.search(r'const APP_VERSION = "([^"]+)"', fh.read())
        self.assertEqual(E.ADDIN_VERSION, m.group(1),
                         "The add-in changed: port its fitting changes, set ADDIN_VERSION, re-run make_golden.py")

    def test_example_data(self):
        for mode in ("melt", "uv", "spec"):
            self.assertEqual(E.example_data(mode), GOLDEN["__example"][mode], mode)


class Formatting(unittest.TestCase):
    """JavaScript number formatting, against values worked out by hand from the ECMAScript rules."""

    def test_to_fixed(self):
        for x, d, want in [(2.5, 0, "3"), (0.125, 2, "0.13"), (-0.0001, 2, "-0.00"), (1.005, 2, "1.00"),
                           (42.5, 1, "42.5"), (1e21, 2, "1e+21"), (-1.5, 0, "-2"), (0, 3, "0.000")]:
            self.assertEqual(E.js_to_fixed(x, d), want, (x, d))

    def test_to_precision_and_str(self):
        for x, p, want in [(123.456, 4, "123.5"), (0.000123456, 3, "0.000123"), (1e-7, 2, "1.0e-7"),
                           (99999, 4, "1.000e+5"), (9.995, 3, "9.99"), (5, 1, "5"), (0, 3, "0.00")]:
            self.assertEqual(E.js_to_precision(x, p), want, (x, p))
        for x, want in [(0.00005, "0.00005"), (1e-7, "1e-7"), (1e21, "1e+21"), (123456789012, "123456789012"),
                        (0.1, "0.1"), (-2.5e-8, "-2.5e-8"), (100, "100")]:
            self.assertEqual(E.js_str(x), want, x)
        self.assertEqual(E.fmt_num(8.111e-4), "8.111E-4")
        self.assertEqual(E.fmt_pm(42.5876, 0.0891), "42.588 ± 0.089")


if __name__ == "__main__":
    unittest.main(verbosity=2)
