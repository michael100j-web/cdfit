"""The command line and the Word round trip.  Run:  py skill/tests/test_cli.py"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cdfit", "scripts"))
import cdfit  # noqa: E402
import cdfit_engine as E  # noqa: E402
import cdfit_word as W  # noqa: E402


def read(path, encoding="utf-8"):
    with open(path, encoding=encoding) as fh:
        return fh.read()


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cdfit.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cdfit-test-")
        for mode in ("melt", "uv", "spec"):
            with open(os.path.join(cls.tmp, f"{mode}.txt"), "w", encoding="utf-8") as fh:
                fh.write(E.example_data(mode))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.tmp, *p)

    def results(self, name, out):
        with open(self.path(out, f"{name}_results.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_melt_with_word_file_round_trip(self):
        code, out, _ = run("fit", self.path("melt.txt"), "--out", self.path("m1"), "--docx")
        self.assertEqual(code, 0)
        self.assertIn("CMP-1: Tm = 42.588 ± 0.089 °C (95% CI 42.41 to 42.77)", out)
        self.assertIn("ΔH fixed at −500 kJ/mol", out)
        for f in ("melt.png", "melt_results.tsv", "melt_results.json", "melt_state.json", "melt.docx"):
            self.assertTrue(os.path.exists(self.path("m1", f)), f)
        res = self.results("melt", "m1")
        self.assertEqual([s["status"] for s in res["series"]], ["fitted", "fitted"])
        self.assertAlmostEqual(res["series"][0]["Tm"]["value"], 42.5884, places=3)
        # the Word file: one picture with the add-in's title and alt text, one table, the state intact
        graphs = W.read_graphs(self.path("m1", "melt.docx"))
        self.assertEqual(len(graphs), 1)
        with open(self.path("m1", "melt_state.json"), encoding="utf-8") as fh:
            self.assertEqual(graphs[0]["state"], json.load(fh))
        self.assertTrue(graphs[0]["summary"].startswith("CD melting curve fitted with CD Fit. CMP-1: Tm = 42.588"))
        with zipfile.ZipFile(self.path("m1", "melt.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn('title="CD Fit graph #', xml)
        self.assertIn("&#10;&#10;DATA (columns separated by ;)", xml)
        self.assertIn("---- CD Fit settings (used by the add-in) ----&#10;#CDFIT-STATE {", xml)
        self.assertEqual(xml.count("<w:tbl>"), 1)
        # re-fitting the graph from the Word file gives the same numbers, and options apply on top
        code, out, _ = run("fit", self.path("m1", "melt.docx"), "--out", self.path("m2"), "--direction", "down")
        self.assertEqual(code, 0)
        self.assertIn("[graph1]", out)
        self.assertIn("signal falls on unfolding", out)
        self.assertIn("CMP-1: Tm = 42.588 ± 0.089 °C", out)
        code, out, _ = run("list", self.path("m1", "melt.docx"))
        self.assertEqual(code, 0)
        self.assertIn("1. CD melting · 2 data set(s)", out)

    def test_uv_defaults_and_dh_options(self):
        code, out, _ = run("fit", self.path("uv.txt"), "--mode", "uv", "--out", self.path("u1"))
        self.assertEqual(code, 0)
        self.assertIn("signal rises on unfolding", out)
        self.assertIn("(constrained ≥ 0)", read(self.path("u1", "uv_results.tsv"), "utf-8-sig"))
        code, out, _ = run("fit", self.path("uv.txt"), "--mode", "uv", "--fit-dH", "--out", self.path("u2"))
        self.assertIn("ΔH fitted", out)
        self.assertIn("H", self.results("uv", "u2")["series"][0]["params"])
        code, out, _ = run("fit", self.path("uv.txt"), "--mode", "uv", "--dH=-400000", "--out", self.path("u3"))
        self.assertIn("ΔH fixed at −400 kJ/mol", out)
        self.assertIn("H=-400000", self.results("uv", "u3")["equation"])
        code, _, err = run("fit", self.path("uv.txt"), "--dH=-4e5", "--fit-dH", "--out", self.path("u4"))
        self.assertEqual(code, 2)
        self.assertIn("either --dH or --fit-dH", err)

    def test_spectrum(self):
        code, out, _ = run("fit", self.path("spec.txt"), "--mode", "spec", "--out", self.path("s1"),
                           "--formats", "png,svg,pdf")
        self.assertEqual(code, 0)
        self.assertIn("CMP-1 (4 °C): max 225 nm (2.479), min 197.5 nm (-38.26), crossover 217.5 nm, Rpn 0.065", out)
        for ext in ("png", "svg", "pdf"):
            self.assertTrue(os.path.exists(self.path("s1", f"spec.{ext}")))
        self.assertEqual(self.results("spec", "s1")["series"][0]["bands"]["xMax"], 225)

    def test_columns_names_xrange_and_options(self):
        code, out, _ = run("fit", self.path("melt.txt"), "--out", self.path("c1"), "--columns", "2",
                           "--names", "first|second", "--xrange", "15", "", "--start", "Tm=30", "--fix", "DEN=-0.006",
                           "--set", "tmLine=true", "--legend", "bl", "--ytitle", "*A*_{215}")
        self.assertEqual(code, 0)
        res = self.results("melt", "c1")
        self.assertEqual([s["status"] for s in res["series"]], ["hidden", "fitted"])
        self.assertEqual(res["series"][1]["name"], "second")
        self.assertEqual(res["series"][1]["excluded"], 5)
        self.assertTrue(res["series"][1]["params"]["DEN"]["fixed"])
        with open(self.path("c1", "melt_state.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        self.assertEqual((st["xFrom"], st["xTo"], st["fmt"]["tmLine"], st["fmt"]["legend"]), ("15", "", True, "bl"))
        code, _, err = run("fit", self.path("melt.txt"), "--set", "colour=red", "--out", self.path("c2"))
        self.assertEqual(code, 2)
        self.assertIn("unknown graph setting", err)
        code, _, err = run("fit", self.path("melt.txt"), "--columns", "7", "--out", self.path("c3"))
        self.assertEqual(code, 2)
        self.assertIn("no column '7'", err)

    def test_xlsx_and_jasco_inputs(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        p = E.parse_data(E.example_data("melt"))
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["T (°C)", *p["names"]])
        for r in p["rows"]:
            ws.append(r)
        wb.save(self.path("melt.xlsx"))
        code, out, _ = run("fit", self.path("melt.xlsx"), "--out", self.path("x1"))
        self.assertEqual(code, 0)
        self.assertIn("CMP-1: Tm = 42.588 ± 0.089 °C", out)
        rows = E.example_data("melt").split("\n")[1:]
        jasco = ["TITLE\tCMP-1", "DATA TYPE\t", "ORIGIN\tJASCO", "XUNITS\tTemperature [C]", "YUNITS\tCD [mdeg]",
                 "NPOINTS\t51", "XYDATA"] + ["\t".join(r.split("\t")[:2]) for r in rows] + \
                ["", "##### Extended Information", "[Comments]", "Sample name\tCMP-1"]
        with open(self.path("jasco.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(jasco))
        code, out, _ = run("fit", self.path("jasco.txt"), "--out", self.path("j1"))
        self.assertEqual(code, 0)
        self.assertIn("CD [mdeg]: Tm = 42.588 ± 0.089 °C", out)

    def test_failed_fit_and_equation_error(self):
        with open(self.path("tiny.txt"), "w") as fh:
            fh.write("T\tY\n10\t1\n20\t2\n30\t3\n")
        code, out, _ = run("fit", self.path("tiny.txt"), "--out", self.path("e1"))
        self.assertEqual(code, 1)
        self.assertIn("fit failed: Only 3 points for 5 free parameters.", out)
        code, out, _ = run("fit", self.path("melt.txt"), "--equation", "Y=A*(X+", "--out", self.path("e2"))
        self.assertEqual(code, 1)
        self.assertIn("Equation error: Line 1: expression ends unexpectedly", out)

    def test_scripts_parse_on_older_python(self):
        """claude.ai's sandbox runs an older Python than this machine may: no 3.12-only syntax."""
        import ast
        folder = os.path.join(HERE, "..", "cdfit", "scripts")
        for name in os.listdir(folder):
            if name.endswith(".py"):
                ast.parse(read(os.path.join(folder, name)), filename=name, feature_version=(3, 8))

    def test_skill_frontmatter(self):
        text = read(os.path.join(HERE, "..", "cdfit", "SKILL.md"))
        self.assertTrue(text.startswith("---\nname: cdfit\ndescription: "))
        desc = text.split("description: ", 1)[1].split("\n", 1)[0]
        self.assertLessEqual(len(desc), 1024)
        self.assertNotIn("<", desc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
