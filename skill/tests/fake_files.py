"""Fabricated spectrometer exports for the tests: a Chirascan (Pro-Data) melting scan and spectrum, a JASCO export of
spectra at several temperatures, and a plain CSV scan. The layouts follow real exports; the numbers come from the
CMP model with a known Tm plus seeded noise. No measured data."""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cdfit", "scripts"))
import cdfit_engine as E  # noqa: E402

CRLF = "\r\n"
_FN = E.compile_model(E.PRESETS["cmp"]["text"]).fn


class Noise:
    def __init__(self, seed=11):
        self.seed = seed

    def __call__(self, sd):
        self.seed = (self.seed * 16807) % 2147483647
        a = self.seed / 2147483647
        self.seed = (self.seed * 16807) % 2147483647
        b = self.seed / 2147483647
        return sd * math.sqrt(-2 * math.log(a + 1e-12)) * math.cos(2 * math.pi * b)


def cd225(t, tm):
    """CD at 225 nm in mdeg: positive when folded, near zero unfolded."""
    return 0.32 * _FN(t, [tm, 38.75, -0.11, 16.0, -0.005]) - 4.0


def a225(t, tm):
    """Absorbance at 225 nm: rises on unfolding."""
    return _FN(t, [tm, 0.6836, 0.0008, 0.656, 0.0005])


def _gauss(x, c, w):
    return math.exp(-(((x - c) / w) ** 2))


def cd_spectrum(x, folded):
    return folded * 8.0 * _gauss(x, 225, 7.5) - 60 * _gauss(x, 197.5, 6.5) * (0.6 + 0.4 * folded)


def _head(description, dims, props, temperature="24.26"):
    lines = ["ProDataCSV", "", "Title: Fri Jan  2 10:00:00 2026", "", "Remarks:", "#User: Chirascan User",
             "#Date: 2026/01/02", "#Instrument: 0000", f"#Description:  {description}", "#Concentration: 200 uM",
             "#Pathlength: 1 mm", f"#Temperature: {temperature} C", "", "Last Modified: Fri Jan  2 11:00:00 2026 by unknown.",
             "", "Options:", "", f"Available Dimensions:,{len(dims)}", *dims, "", f"Available Properties: ,{len(props)}",
             *[p + "," for p in props], "", "Data:", ""]
    return lines


def _tail():
    return ["", "", "History: ", "User : Chirascan User\r", "Version : Pro-Data v.0.0.0 Build : Aug 26 2021 13:36:27",
            "DataStore created and initialized for data acquisition.", "", "----------------------------------------------------", "", ""]


def chirascan_scan(description="CMP-A", tm=40.0, waves=(285, 265, 245, 225, 205), t0=10.0, t1=70.0, step=0.5,
                   absorbance=True, seed=11):
    """A temperature ramp with the CD (and absorbance) read at a few wavelengths at each temperature."""
    noise = Noise(seed)
    temps = [round(t0 + i * step, 6) for i in range(int(round((t1 - t0) / step)) + 1)]
    temps = [int(t) if t == int(t) else t for t in temps]
    props = ["CircularDichroism", "HV"] + (["Absorbance"] if absorbance else []) + ["Temperature"]
    dims = [f"Temperature,{len(temps)} temperatures, from {E.js_str(t0)} to {E.js_str(t1)}degrees Celsius  in smooth ramp mode "
            "at ramp-rate of 0.5degrees C per min.",
            f"Wavelength,Wavelength: {min(waves)}nm - {max(waves)}nm,Step Size: 20nm,Bandwidth: 1nm"]
    lines = _head(description, dims, props)

    def value(prop, t, w):
        if prop == "CircularDichroism":
            if w == 225:
                return cd225(t, tm) + noise(0.08)
            folded = 1 / (1 + math.exp((t - tm) / 3))
            return cd_spectrum(w, folded) * 0.3 + noise(0.08)
        if prop == "HV":
            return 300 + 0.5 * t + (285 - w) + noise(0.5)
        if prop == "Absorbance":
            return (a225(t, tm) if w == 225 else 0.2 + 0.001 * t) + noise(0.002)
        return t - 5 + noise(3)   # the Temperature property is not the axis

    for prop in props:
        lines += ["", prop, "Temperature,Wavelength", "," + ",".join(str(w) for w in waves) + ","]
        for t in temps:
            lines.append(",".join([E.js_str(t)] + [f"{value(prop, t, w):.6g}" for w in waves]))
    return CRLF.join(lines + _tail())


def chirascan_spectrum(description="CMP-A", temperature="24.26", folded=1.0, lo=180, hi=300, seed=5):
    """A CD spectrum: one block per property, each "Wavelength," then the property name."""
    noise = Noise(seed)
    dims = [f"Wavelength,Wavelength: {lo}nm - {hi}nm,Step Size: 1nm,Bandwidth: 1nm"]
    props = ["CircularDichroism", "HV", "Absorbance"]
    lines = _head(description, dims, props, temperature)
    for prop in props:
        lines += ["Wavelength,", prop]
        for x in range(hi, lo - 1, -1):
            v = cd_spectrum(x, folded) * 0.3 + noise(0.05) if prop == "CircularDichroism" else \
                (250 + (300 - x) * 2 + noise(0.5) if prop == "HV" else 0.1 + 0.02 * (300 - x) + noise(0.002))
            lines.append(f"{x},{v:.6g}")
        lines.append("")
    return CRLF.join(lines + _tail())


def jasco_matrix(title="CMP-B", tm=35.0, temps=(5, 15, 25, 30, 35, 40, 45, 55, 65), seed=3):
    """A JASCO export of spectra at several temperatures: a row of temperatures over the spectra."""
    noise = Noise(seed)
    lines = [f"TITLE\t{title}", "DATA TYPE\t", "ORIGIN\tJASCO", "XUNITS\tNANOMETERS", "YUNITS\tCD [mdeg]",
             "FIRSTX\t260.0000", "LASTX\t190.0000", "NPOINTS\t71", "XYDATA", "\t" + "\t".join(str(t) for t in temps)]
    for x in range(260, 189, -1):
        cells = []
        for t in temps:
            folded = (cd225(t, tm) + 4.0) / (cd225(-20, tm) + 4.0)
            cells.append(f"{cd_spectrum(x, folded) * 0.3 + noise(0.05):.4f}")
        lines.append(f"{x}.0000\t" + "\t".join(cells))
    return "\n".join(lines + ["", "##### Extended Information", "[Comments]", "Sample name\tCMP-B"])


def plain_scan(tm=45.0, seed=8):
    """A spreadsheet of a scan: temperature down, a CD and an HT column per wavelength across."""
    noise = Noise(seed)
    waves = (222, 225, 230)
    lines = ["Temperature (°C)," + ",".join(f"CD {w} nm,HT {w} nm" for w in waves)]
    for i in range(61):
        t = 10 + i
        cells = []
        for w in waves:
            cells += [f"{cd225(t, tm) * (1 - abs(w - 225) / 40) + noise(0.08):.4f}", f"{300 + t:.1f}"]
        lines.append(f"{t}," + ",".join(cells))
    return "\n".join(lines)
