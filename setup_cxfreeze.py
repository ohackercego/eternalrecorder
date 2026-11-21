"""cx_Freeze: gera a pasta `dist_cxfreeze` com `Eternal Recorder.exe`.

POR QUE cx_FREEZE E NAO SO PYINSTALLER
======================================
Pedido do usuário: "o release tem que ter SEMPRE o .exe via cx_freeze".
A pasta do cx_Freeze é mais previsível para este app que o onefile: os locales
JSON, as DLLs do libobs e os módulos de dados ficam em disco, do lado do exe,
e um arquivo faltando aparece como erro claro em vez de um exe que abre sem
idioma.

Uso:
    python setup_cxfreeze.py build_exe --build-exe dist_cxfreeze

ARMADILHAS QUE JÁ CUSTARAM TEMPO AQUI
=====================================
1. **A versão era hardcoded ("2.1.2")** e o exe saía com número errado mesmo
   com o VERSION em outro. Agora lê o arquivo VERSION.
2. **`ui/locales/*.json` tem que ir como `include_files`**, senão o exe abre
   com a chave crua na tela (`app.name`) porque o i18n resolve `ui/locales`
   relativo ao exe congelado.
3. **`base="Win32GUI"`** esconde o console — obrigatório num app para leitor
   de tela, senão uma janela preta aparece atrás.
4. **`_sounddevice_data`** carrega a PortAudio DLL; sem ela os bipes do
   `ui/tones.py` morrem em silêncio.
5. **`obs-amf-test.exe` / `obs-*-test.exe`** vêm junto do pylibobs e não fazem
   mal; não tente removê-los.
"""
from __future__ import annotations

from pathlib import Path

from cx_Freeze import Executable, setup

RAIZ = Path(__file__).resolve().parent


def _versao() -> str:
    """A versão vem do arquivo VERSION — nunca duplicar o número aqui."""
    try:
        v = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
        return v or "0.0.0"
    except Exception:
        return "0.0.0"


# locales da UI: sem isto o exe mostra as chaves cruas na tela
_locales = sorted((RAIZ / "ui" / "locales").glob("*.json"))

build_exe_options = {
    "packages": ["pylibobs", "wx", "av", "sounddevice", "numpy",
                 "accessible_output2", "engine", "ui"],
    "include_files": [(str(p), f"ui/locales/{p.name}") for p in _locales],
    "excludes": ["tkinter", "matplotlib", "pandas", "PIL"],
    "include_msvcr": True,
}

setup(
    name="Eternal Recorder",
    version=_versao(),
    description="Gravador de tela acessível para leitores de tela",
    options={"build_exe": build_exe_options},
    executables=[Executable("launcher.py", base="Win32GUI",
                            target_name="Eternal Recorder")],
)
