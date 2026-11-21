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


def _crt_dlls() -> list[tuple[str, str]]:
    """As DLLs do runtime C++ que o exe precisa para ABRIR.

    `objdump -p` mostra que o exe importa VCRUNTIME140.dll. O cx_Freeze só as
    copia com `include_msvcr`, que **baixa** o redistributable da Microsoft —
    sem rede o build morre em `getaddrinfo failed` e o exe sai quebrado em
    qualquer máquina sem o VC++ Redist. Aqui elas vêm do próprio Python que
    está construindo, sem tocar na rede.
    """
    import sys
    from pathlib import Path as _P

    origem = _P(sys.base_prefix)
    achadas: list[tuple[str, str]] = []
    for nome in ("vcruntime140.dll", "vcruntime140_1.dll",
                 "msvcp140.dll", "concrt140.dll"):
        p = origem / nome
        if p.exists():
            achadas.append((str(p), nome))
    return achadas

build_exe_options = {
    "packages": ["pylibobs", "wx", "av", "sounddevice", "numpy",
                 "accessible_output2", "engine", "ui"],
    "include_files": [(str(p), f"ui/locales/{p.name}") for p in _locales]
                     + _crt_dlls(),
    "excludes": ["tkinter", "matplotlib", "pandas", "PIL"],
    # NÃO use include_msvcr: ele tenta BAIXAR o redistributable da Microsoft e,
    # sem rede, o build termina com "getaddrinfo failed" e o exe sai sem o
    # VCRUNTIME140.dll — quebra em qualquer PC sem o VC++ Redist instalado.
    # As DLLs do CRT vêm do próprio Python que está construindo, logo abaixo.
    "include_msvcr": False,
}

setup(
    name="Eternal Recorder",
    version=_versao(),
    description="Gravador de tela acessível para leitores de tela",
    options={"build_exe": build_exe_options},
    executables=[Executable("launcher.py", base="Win32GUI",
                            target_name="Eternal Recorder")],
)


# ── cópia do CRT DEPOIS do build ───────────────────────────────────────────
# O `include_files` do cx_Freeze coloca os arquivos em `lib/`, mas o exe
# importa VCRUNTIME140.dll da RAIZ da pasta (é o loader do Windows que resolve
# a importação, antes de qualquer sys.path). Sem esta cópia o exe só abre em
# máquina que já tem o VC++ Redistributable instalado — e falha calada com
# "não foi possível iniciar o aplicativo" em qualquer outra.
def _copiar_crt_para_raiz() -> None:
    import shutil
    import sys
    from pathlib import Path as _P

    # o diretório de saída é o último argumento de --build-exe, ou o padrão
    saida = None
    for i, a in enumerate(sys.argv):
        if a == "--build-exe" and i + 1 < len(sys.argv):
            saida = _P(sys.argv[i + 1])
        elif a.startswith("--build-exe="):
            saida = _P(a.split("=", 1)[1])
    saida = saida or (RAIZ / "build" / "exe.win-amd64-3.12")
    if not (saida / "Eternal Recorder.exe").exists():
        return
    for nome in ("vcruntime140.dll", "vcruntime140_1.dll",
                 "msvcp140.dll", "concrt140.dll"):
        origem = _P(sys.base_prefix) / nome
        if origem.exists():
            destino = saida / nome
            if not destino.exists():
                shutil.copy2(origem, destino)


import atexit as _atexit

_atexit.register(_copiar_crt_para_raiz)
