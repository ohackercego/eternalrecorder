# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: um único executável do Eternal Recorder.
# libobs precisa das DLLs obs-plugins em runtime — são coletadas do
# pylibobs pelos hooks de dados abaixo.

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("pylibobs")
binarios = collect_dynamic_libs("pylibobs")
# accessible_output2 carrega DLLs de braille/fala
datas += collect_data_files("accessible_output2")
# os locales JSON da UI (i18n lê de sys._MEIPASS/ui/locales no exe)
datas += [(".", "ui/locales")] if False else [
    (str(p), "ui/locales")
    for p in __import__("pathlib").Path("ui/locales").glob("*.json")]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binarios,
    datas=datas,
    hiddenimports=[
        "pylibobs",
        "pylibobs.scene",
        "pylibobs.source",
        "pylibobs.output",
        "pylibobs.properties",
        "accessible_output2.outputs.auto",
        "accessible_output2.outputs.nvda",
        "accessible_output2.outputs.sapi",
        "sounddevice",
        "av",
        "wx",
        "wx.adv",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Eternal Recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
