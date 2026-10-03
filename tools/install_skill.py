"""Install the CD Fit skill for Claude Code and build the zip for claude.ai.

  py tools/install_skill.py              copy skill/cdfit to ~/.claude/skills/cdfit and write dist/cdfit-skill.zip
  py tools/install_skill.py --zip-only   only write the zip

In claude.ai, upload dist/cdfit-skill.zip under Customize > Skills > + > Create skill > Upload a skill,
or, as an Owner, under Organization settings > Plugins & skills > Add > Upload a skill for everyone.
"""
import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skill" / "cdfit"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def files():
    for path in sorted(SRC.rglob("*")):
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(SRC).parts) and path.suffix != ".pyc":
            yield path


def build_zip():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / "cdfit-skill.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files():
            zf.write(path, "cdfit/" + path.relative_to(SRC).as_posix())   # the skill folder at the zip's root
    return out


def install():
    dst = Path.home() / ".claude" / "skills" / "cdfit"
    if dst.exists():
        skill_md = dst / "SKILL.md"
        if not skill_md.exists() or "name: cdfit" not in skill_md.read_text(encoding="utf-8"):
            sys.exit(f"{dst} exists and is not the CD Fit skill; not touching it.")
        shutil.rmtree(dst)
    for path in files():
        target = dst / path.relative_to(SRC)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zip-only", action="store_true", help="only build dist/cdfit-skill.zip")
    a = ap.parse_args()
    if not a.zip_only:
        print(f"Installed for Claude Code: {install()}")
    print(f"Zip for claude.ai: {build_zip()}")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
