# PyInstaller spec for the Vocab desktop app.
#
#     pyinstaller packaging/vocab.spec --noconfirm
#
# Set VOCAB_CONSOLE=1 for a build that shows errors in a console window.
# Produces dist/Vocab/ (a folder, which starts faster than a single-file exe).
# The BHSA database must have been built first (python build_db.py).

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
DB = ROOT / "data" / "bhsa_vocab.sqlite"
if not DB.exists():
    raise SystemExit(f"{DB} is missing: run build_db.py first")

# Anaconda's Python keeps sqlite3.dll in Library/bin, where PyInstaller does not
# look; include it explicitly. (A python.org Python has it next to _sqlite3.pyd.)
import sys
binaries = []
conda_sqlite = Path(sys.base_prefix) / "Library" / "bin" / "sqlite3.dll"
if conda_sqlite.exists():
    binaries.append((str(conda_sqlite), "."))

a = Analysis(
    [str(ROOT / "vocab_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[
        (str(DB), "data"),
        (str(ROOT / "fonts"), "fonts"),
        (str(ROOT / "packaging" / "vocab.ico"), "packaging"),
    ],
    hiddenimports=["fsrs_rs_python"],
    excludes=["tkinter", "tf", "pandas", "numpy", "matplotlib", "IPython", "pytest",
              "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
              "PySide6.QtOpenGL", "PySide6.QtPdf", "PySide6.QtDBus"],
    noarchive=False,
)
# Software OpenGL (20 MB) is not needed by a Qt Widgets app.
a.binaries = [b for b in a.binaries if not b[0].endswith("opengl32sw.dll")]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vocab",
    icon=str(ROOT / "packaging" / "vocab.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=bool(os.environ.get("VOCAB_CONSOLE")),   # set VOCAB_CONSOLE=1 to see errors
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Vocab", upx=False)
