# -*- mode: python ; coding: utf-8 -*-
#
# labelImg.spec — PyInstaller build spec for labelImg
#
# Build:
#   pyinstaller labelImg.spec
#
# NOTE: Do NOT use UPX compression — it increases antivirus false positive rate.

a = Analysis(
    ['labelImg.py'],
    pathex=['.'],                       # project root, for `from libs.xxx import *` to work
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt5 submodules (wildcard imports throughout the codebase)
        'PyQt5.QtGui',
        'PyQt5.QtCore',
        'PyQt5.QtWidgets',
        # lxml
        'lxml.etree',
        'lxml._elementpath',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # not needed and would bloat the exe
        'tkinter',
        'matplotlib',
    ],
    noarchive=False,
    # keep bytecode readable for debugging; can bump to 2 later
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='labelImg',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                          # UPX → more AV false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                      # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources\\icons\\app.png'],
)
