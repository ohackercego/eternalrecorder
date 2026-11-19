"""Launcher do Eternal Recorder (UI Python).

O Python embarcado do app não tem `pip` e usa um `._pth` restrito: só
`Lib/site-packages` do próprio runtime e a pasta do script entram no
`sys.path`. Por isso o caminho do repositório é injetado aqui, antes de
qualquer import da UI.

Uso:
    python launcher.py            # abre a janela
    python launcher.py --teste    # auto-teste (grava 5 s e valida o arquivo)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# dependências: no runtime empacotado ficam em Lib/site-packages; no venv de
# desenvolvimento o caminho já está no sys.path
_SITE = RAIZ / "Lib" / "site-packages"
if _SITE.is_dir() and str(_SITE) not in sys.path:
    sys.path.insert(0, str(_SITE))

# localiza as dependências instaladas nesta máquina (desenvolvimento)
if os.environ.get("ETERNAL_SITE"):
    for p in os.environ["ETERNAL_SITE"].split(os.pathsep):
        if p and p not in sys.path:
            sys.path.insert(0, p)


def _checar_dependencias() -> list[str]:
    faltando = []
    for mod, pacote in (("wx", "wxPython"),
                        ("accessible_output2", "accessible-output2"),
                        ("pylibobs", "pylibobs"),
                        ("av", "av")):
        try:
            __import__(mod)
        except Exception:
            faltando.append(pacote)
    return faltando


def main() -> int:
    args = sys.argv[1:]
    faltando = _checar_dependencias()
    if faltando:
        print("Faltam dependências: " + ", ".join(faltando), file=sys.stderr)
        print("Instale com: pip install " + " ".join(faltando), file=sys.stderr)
        return 2

    if "--teste" in args:
        # reusa o auto-teste (import tardio para não exigir wx sem GUI)
        sys.path.insert(0, str(Path(os.environ.get("TEMP", "."))))
        try:
            import testar_ui_motor as t
            return t.main()
        except ImportError:
            print("teste não encontrado; use a janela normalmente",
                  file=sys.stderr)
            return 3

    from ui.app import main as ui_main
    return ui_main()


if __name__ == "__main__":
    sys.exit(main())
