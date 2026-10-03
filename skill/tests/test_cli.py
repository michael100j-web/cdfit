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
        self.assertIn("jasco: Tm = 42.588 ± 0.089 °C", out)   # the CD channel, named after the file

    def test_many_spectra_at_once(self):
        """Several JASCO spectrum files in one go: one column each (CD channel only), in temperature order, a row
        per spectrum, and θ at 225 nm against temperature written out ready for a melting fit."""
        import math
        g = lambda x, c, w: math.exp(-(((x - c) / w) ** 2))
        os.makedirs(self.path("many"), exist_ok=True)
        files = []
        for t in (60, 4, 20, 40, 30, 50, 80):          # given out of order
            f = 1 / (1 + math.exp((t - 42) / 3))
            lines = ["TITLE\tCMP1", "XUNITS\tNANOMETERS", "YUNITS\tCD [mdeg]", "Y2UNITS\tHT [V]", "XYDATA"]
            lines += [f"{x}\t{f * 4.3 * g(x, 225, 7.5) - 39 * g(x, 197.5, 6.5):.4f}\t{300 + x:.1f}" for x in range(260, 189, -1)]
            path = self.path("many", f"CMP1_{t}C.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines + ["", "##### Extended Information"]))
            files.append(path)
        code, out, _ = run("fit", *files, "--mode", "spec", "--out", self.path("s2"))
        self.assertEqual(code, 0)
        names = [l.split(":")[0].strip() for l in out.splitlines() if l.startswith("  CMP1_")]
        self.assertEqual(names, ["CMP1_4C", "CMP1_20C", "CMP1_30C", "CMP1_40C", "CMP1_50C", "CMP1_60C", "CMP1_80C"])
        self.assertNotIn("HT", out)
        self.assertIn("θ at 225 nm against temperature, fitted with the CMP model (ΔH −500 kJ/mol): CMP1 Tm = ", out)
        self.assertTrue(os.path.exists(self.path("s2", "CMP1_melt_225nm.png")))
        table = read(self.path("s2", "CMP1_spectra.tsv"), "utf-8-sig").strip().split("\n")
        self.assertEqual(len(table), 8)
        self.assertEqual(table[0].split("\t")[:3], ["Spectrum", "T (°C)", "λ max (nm)"])
        self.assertEqual(table[1].split("\t")[:2], ["CMP1_4C", "4"])
        melt = self.path("s2", "CMP1_melt_225nm.txt")
        self.assertEqual(read(melt).split("\n")[0], "T (°C)\tCMP1")
        code, out, _ = run("fit", melt, "--mode", "melt", "--out", self.path("s3"))
        self.assertEqual(code, 0)
        tm = float(out.split("Tm = ")[1].split(" ")[0])
        self.assertAlmostEqual(tm, 42, delta=1.0)
        with open(self.path("many", "report.docx"), "wb") as fh:
            fh.write(b"PK")
        code, _, err = run("fit", files[0], self.path("many", "report.docx"), "--out", self.path("s4"))
        self.assertEqual(code, 2)
        self.assertIn("only be fitted on its own", err)

    def test_spectrometer_files(self):
        """A Chirascan melting scan gives CD at 225 nm against temperature (absorbance in UV melting), its spectra
        open in spectrum mode, and a JASCO table of spectra and a spreadsheet scan give the 225 nm curve too. The
        files are fabricated (fake_files.py) with known Tm values."""
        import fake_files as FF
        d = self.path("instr")
        os.makedirs(d, exist_ok=True)
        files = {"CMPA_Tm.csv": FF.chirascan_scan(tm=40.0), "CMPA_CD.csv": FF.chirascan_spectrum(),
                 "CMPA_CD_hot.csv": FF.chirascan_spectrum(temperature="80.1", folded=0.0, seed=9),
                 "cmpB_jasco.txt": FF.jasco_matrix(tm=35.0), "scan_sheet.csv": FF.plain_scan(tm=45.0)}
        for name, text in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        f = lambda name: os.path.join(d, name)
        tm = lambda out: float(out.split("Tm = ")[1].split(" ")[0])
        code, out, _ = run("fit", f("CMPA_Tm.csv"), "--out", self.path("c1"))
        self.assertEqual(code, 0)
        self.assertIn("read: CMPA_Tm: CD at 225 nm against temperature (Chirascan scan at 205–285 nm every 20 nm, "
                      "121 temperatures).", out)
        self.assertAlmostEqual(tm(out), 40, delta=0.5)
        self.assertEqual(self.results("CMPA_Tm", "c1")["series"][0]["name"], "CMPA_Tm")
        self.assertEqual(json.loads(read(self.path("c1", "CMPA_Tm_state.json")))["fmt"]["yTitle"], "*θ*_{225} (mdeg)")
        code, out, _ = run("fit", f("CMPA_Tm.csv"), "--mode", "uv", "--out", self.path("c2"))
        self.assertEqual(code, 0)
        self.assertIn("absorbance at 225 nm against temperature", out)
        self.assertAlmostEqual(tm(out), 40, delta=0.5)
        code, _, err = run("fit", f("CMPA_Tm.csv"), "--wavelength", "222", "--out", self.path("c3"))
        self.assertEqual(code, 2)
        self.assertIn("no 222 nm: measured at 205–285 nm every 20 nm", err)
        code, _, err = run("fit", f("CMPA_Tm.csv"), "--mode", "spec", "--out", self.path("c4"))
        self.assertEqual(code, 2)
        self.assertIn("a melting scan at 205–285 nm every 20 nm: use --mode melt", err)
        code, out, _ = run("fit", f("CMPA_CD_hot.csv"), f("CMPA_CD.csv"), "--out", self.path("c5"))
        self.assertEqual(code, 0)
        self.assertIn("so they opened in CD spectrum", out)
        self.assertIn("CMPA_CD (24.26 °C): max 225 nm", out)
        self.assertLess(out.index("CMPA_CD (24.26"), out.index("CMPA_CD_hot (80.1"))   # natural order of the names
        self.assertNotIn("HV", read(self.path("c5", "CMPA_CD_state.json")))
        code, out, _ = run("fit", f("cmpB_jasco.txt"), "--out", self.path("c6"))
        self.assertEqual(code, 0)
        self.assertIn("read: cmpB_jasco: CD at 225 nm against temperature.", out)
        self.assertAlmostEqual(tm(out), 35, delta=1.5)
        code, out, _ = run("fit", f("scan_sheet.csv"), "--wavelength", "224", "--out", self.path("c7"))
        self.assertEqual(code, 0)
        self.assertIn("CD at 224 nm against temperature (scan at 222, 225, 230 nm, 61 temperatures)", out)
        self.assertAlmostEqual(tm(out), 45, delta=0.5)

    def test_file_readers(self):
        import cdfit_files as F
        self.assertIsNone(F.chirascan(E.example_data("melt")))
        self.assertEqual(F.csv_to_tabs('T,"CD 225 nm, run 1",HT\n10,1.5,300\n'), "T\tCD 225 nm, run 1\tHT\n10\t1.5\t300\n")
        self.assertEqual(F.csv_to_tabs("T\tA\n1\t2"), "T\tA\n1\t2")          # already tabs
        self.assertEqual(F.csv_to_tabs("1,5 2,5\n3,5 4,5"), "1,5 2,5\n3,5 4,5")   # decimal commas, spaces between
        self.assertEqual(F.nm_in("CD 225 nm")["w"], 225)
        self.assertEqual(F.nm_in("A280")["w"], 280)
        self.assertEqual(F.pick_wave([205, 225, 245], 225), {"k": 1})
        self.assertIsNone(F.pick_wave([205, 225, 245], 222))                 # 20 nm apart: not interpolated
        self.assertEqual(F.pick_wave([222, 225], 224)["lo"], 0)

    def test_spectrum_labels(self):
        import cdfit_spectra as SP
        self.assertEqual(SP.label_of("CMP-1 (4 °C)"), {"value": 4.0, "celsius": True, "group": "CMP-1"})
        self.assertEqual(SP.label_of("CMP1_20.5C"), {"value": 20.5, "celsius": True, "group": "CMP1"})
        self.assertEqual(SP.label_of("sample 37")["value"], 37.0)
        self.assertFalse(SP.label_of("sample 37")["celsius"])
        self.assertTrue(SP.label_of("20")["celsius"])       # a bare number over a spectrum is its temperature
        self.assertFalse(SP.label_of("200")["celsius"])
        self.assertIsNone(SP.label_of("blank"))

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
