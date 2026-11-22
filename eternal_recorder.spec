# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o Eternal Recorder.

POR QUE PYINSTALLER E NAO cx_FREEZE
===================================
O cx_Freeze gerava um exe que morria na abertura com:

    cx_Freeze: Python error in main script (traceback unavailable)
    Cannot import traceback module.
    Exception: No module named 're'

Medido: o `lib/library.zip` saia com 184 entradas e **nenhum modulo da
biblioteca padrao** — nem `re`, nem `json`, nem `traceback`, nem `encodings`.
So pacotes de terceiros (av, cffi, more_itertools, wx...). Ou seja, o freezer
nao coletou a stdlib e o interpretador embutido nao teve como importar `re`.

O PyInstaller traz a stdlib como parte do proprio bootstrap, entao esse modo de
falha nao existe.

DOIS ALVOS, DE PROPOSITO
========================
O pedido foi "uma versao portatil e uma executavel unico".

  * `Eternal Recorder (pasta)/`  — onedir. Abre mais rapido (nada para
    descompactar), e o formato que a pasta `dist/` do repositorio ja usa.
  * `Eternal Recorder.exe`       — onefile. Um arquivo para levar num pendrive.
    Abre mais devagar no primeiro segundo porque extrai para %TEMP%.

Os dois carregam os MESMOS dados: locales (sem eles a UI mostra chave crua),
DLLs do libobs+ffmpeg (81 MB em `pylibobs/_libs/windows/x86_64`) e os icones.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

RAIZ = Path(SPECPATH)

# ------------------------------------------------------------------ dados
# locales: o i18n resolve `ui/locales` relativo ao exe congelado; sem estes
# JSON o programa abre mostrando `app.name` em vez do nome traduzido.
datas = [(str(p), "ui/locales") for p in sorted((RAIZ / "ui" / "locales").glob("*.json"))]

# tudo que o app le do disco em runtime, relativo a raiz do projeto
for pasta, destino in [
    ("ui/locales", "ui/locales"),
    ("docs", "docs"),
]:
    origem = RAIZ / pasta
    if origem.is_dir():
        for p in origem.rglob("*"):
            if p.is_file():
                datas.append((str(p), destino))

for arquivo in ("VERSION", "README.md", "LICENSE", "CHANGELOG.md"):
    p = RAIZ / arquivo
    if p.exists():
        datas.append((str(p), "."))

# DLLs do pylibobs: 81 MB, 27 arquivos (libobs-*, avcodec, avformat, x264...).
# O `_libs` nao e package normal, entao o hook nao o pega sozinho.
_dlls_origem = RAIZ / ".venv-pyinstaller" / "Lib" / "site-packages" / "pylibobs" / "_libs"
binaries = []
if _dlls_origem.is_dir():
    for p in _dlls_origem.rglob("*"):
        if p.is_file():
            # mantem a arvore `_libs/windows/x86_64/...` do lado do exe, que e
            # onde o pylibobs procura em runtime
            rel = p.relative_to(RAIZ / ".venv-pyinstaller" / "Lib" / "site-packages" / "pylibobs")
            binaries.append((str(p), str(Path("pylibobs") / rel.parent)))

# PortAudio: sem esta DLL os bipes de ui/tones.py morrem em silencio
binaries += collect_dynamic_libs("sounddevice")
binaries += collect_dynamic_libs("_sounddevice_data") if _dlls_origem.exists() else []

datas += collect_data_files("sounddevice")

# ------------------------------------------------------------------ escondidos
# imports que so aparecem em runtime (dentro de try/except ou por nome)
hiddenimports = [
    "accessible_output2",
    "accessible_output2.outputs",
    "accessible_output2.outputs.auto",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "sounddevice",
    "_sounddevice_data",
    "wx",
    "wx.adv",
    "wx.html",
    "engine",
    "engine.motor_obs",
    "ui",
    "ui.app",
    "ui.painel_gravacao",
    "ui.painel_config",
    "ui.hotkeys",
    "ui.tones",
    "ui.i18n",
    "ui.accessible",
    "ui.speech",
]

# ---------------------------------------------------------------- exclusoes
excludes = [
    "tkinter",
    "matplotlib",
    "pandas",
    "PIL",
    "pytest",
    "IPython",
    "notebook",
    "PyInstaller",
]

# ------------------------------------------------------------------ alvos
a = Analysis(
    [str(RAIZ / "launcher.py")],
    pathex=[str(RAIZ)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# onedir: pasta com tudo do lado do exe (abre rapido)
exe_pasta = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Eternal Recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # sem console: a janela preta atrapalha leitor de tela
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe_pasta,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Eternal Recorder",
)

# onefile: um arquivo so (para pendrive)
exe_unico = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Eternal Recorder (portatil)",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
