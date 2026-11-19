"""i18n da UI Python: lê os MESMOS JSON de src/locales do build Electron.

Não há motivo para manter duas traduções. O formato já existe, tem 25 idiomas e
177 chaves conferidas; a UI nova só consome as chaves que usa. Chave ausente cai
no inglês e, se nem lá existir, devolve a própria chave — nunca quebra o layout.
"""
from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path
from typing import Any, Optional

# NO EXE (PyInstaller onefile): __file__ aponta para o dir temporário
# _MEIPASS, onde os dados coletados estão. Fora do exe, é o repo.
try:
    _RAIZ = Path(sys._MEIPASS)          # PyInstaller
except AttributeError:
    _RAIZ = Path(__file__).resolve().parent.parent
_LOCAIS = _RAIZ / "ui" / "locales"

_dados: dict[str, Any] = {}
_idioma: str = "en"
_plano: dict[str, str] = {}


def _achatar(d: Any, prefixo: str = "") -> dict[str, str]:
    saida: dict[str, str] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            chave = f"{prefixo}.{k}" if prefixo else str(k)
            if isinstance(v, dict):
                saida.update(_achatar(v, chave))
            else:
                saida[chave] = "" if v is None else str(v)
    return saida


def _detectar() -> str:
    """Idioma do sistema, casando com os arquivos disponíveis."""
    try:
        nome = locale.getlocale()[0] or locale.getdefaultlocale()[0] or "en"
    except Exception:
        nome = "en"
    nome = (nome or "en").replace("_", "-")
    cands = [nome]
    base = nome.split("-")[0]
    if base != nome:
        cands.append(base)
    # variantes chinesas têm arquivo próprio
    if base == "zh":
        cands = ["zh-yue", "zh-TW", "zh", "en"]
    for cand in cands:
        for f in _LOCAIS.glob("*.json"):
            if f.stem.lower() == cand.lower():
                return f.stem
    return "en"


def carregar(idioma: Optional[str] = None) -> str:
    """Carrega o idioma (ou o do sistema). Devolve o código aplicado."""
    global _dados, _idioma, _plano
    escolhido = idioma or _detectar()
    caminho = _LOCAIS / f"{escolhido}.json"
    if not caminho.exists():
        caminho = _LOCAIS / "en.json"
        escolhido = "en"
    try:
        _dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        _dados = {}
    _idioma = escolhido
    base: dict[str, str] = {}
    en = _LOCAIS / "en.json"
    if en.exists() and escolhido != "en":
        try:
            base = _achatar(json.loads(en.read_text(encoding="utf-8")))
        except Exception:
            base = {}
    base.update(_achatar(_dados))       # o idioma escolhido vence
    _plano = base
    return _idioma


def idioma() -> str:
    return _idioma


def t(chave: str, **kwargs: Any) -> str:
    """Traduz uma chave. `{}` no texto é preenchido com os kwargs."""
    if not _plano:
        carregar()
    texto = _plano.get(chave) or chave
    if kwargs:
        try:
            return texto.format(**kwargs)
        except (KeyError, IndexError):
            return texto
    return texto


def disponiveis() -> list[str]:
    return sorted(f.stem for f in _LOCAIS.glob("*.json"))


# idioma padrão ao importar
carregar(os.environ.get("ETERNAL_LANG"))
