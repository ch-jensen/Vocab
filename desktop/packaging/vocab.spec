# PyInstaller spec for the Vocab desktop app (Windows and macOS).
#
#     pyinstaller packaging/vocab.spec --noconfirm
#
# Windows: produces dist/Vocab/ with Vocab.exe (a folder starts faster than a single exe).
#          Set VOCAB_CONSOLE=1 for a build that shows errors in a console window.
# macOS:   produces dist/Vocab.app.
# The BHSA database must have been built first (python build_db.py).

import os
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
DB = ROOT / "data" / "bhsa_vocab.sqlite"
if not DB.exists():
    raise SystemExit(f"{DB} is missing: run build_db.py first")
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (ROOT / "vocab" / "__init__.py").read_text(encoding="utf-8")).group(1)
MAC = sys.platform == "darwin"


def windows_version_file() -> str:
    """Write the Windows version resource for Vocab.exe from vocab.__version__.

    The version is kept in one place (vocab/__init__.py); this fills in both the
    numeric file/product version shown by Windows and the text fields.
    """
    numbers = [int(n) for n in re.findall(r"\d+", VERSION)[:4]]
    numbers += [0] * (4 - len(numbers))
    nums = tuple(numbers)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', 'Vocab'),
      StringStruct('FileDescription', 'Vocab: Biblical Hebrew vocabulary'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('LegalCopyright', 'Christian Canu Højgaard. BHSA data: ETCBC, CC BY-NC 4.0'),
      StringStruct('OriginalFilename', 'Vocab.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = Path(workpath) / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)

# Anaconda's Python keeps sqlite3.dll in Library/bin, where PyInstaller does not
# look; include it explicitly. (A python.org Python has it next to _sqlite3.pyd.)
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
# Software OpenGL (20 MB, Windows only) is not needed by a Qt Widgets app.
a.binaries = [b for b in a.binaries if not b[0].endswith("opengl32sw.dll")]

pyz = PYZ(a.pure)

if MAC:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Vocab",
        console=False,
        upx=False,
        argv_emulation=False,      # Finder file opens arrive as Qt FileOpen events instead
        target_arch=os.environ.get("VOCAB_TARGET_ARCH") or None,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Vocab", upx=False)
    app = BUNDLE(
        coll,
        name="Vocab.app",
        icon=str(ROOT / "packaging" / "vocab.icns"),
        bundle_identifier="io.github.ch-jensen.vocab",
        version=VERSION,
        info_plist={
            "CFBundleName": "Vocab",
            "CFBundleDisplayName": "Vocab",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "BHSA data: ETCBC, CC BY-NC 4.0",
            # .vocabdeck files open in Vocab (double-click in the Finder imports the deck).
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "io.github.ch-jensen.vocab.deck",
                "UTTypeDescription": "Vocab deck",
                "UTTypeConformsTo": ["public.json", "public.data"],
                "UTTypeTagSpecification": {"public.filename-extension": ["vocabdeck"]},
            }],
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Vocab deck",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["io.github.ch-jensen.vocab.deck"],
            }],
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Vocab",
        icon=str(ROOT / "packaging" / "vocab.ico"),
        version=windows_version_file(),
        console=bool(os.environ.get("VOCAB_CONSOLE")),   # set VOCAB_CONSOLE=1 to see errors
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Vocab", upx=False)
