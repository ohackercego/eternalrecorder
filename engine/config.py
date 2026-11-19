"""Configuração persistida: config.ini no mesmo formato do build Electron.

O app antigo grava um INI com seções `[geral]`, `[shortcuts]` e `[recording]`.
Manter o formato permite que as duas versões leiam a mesma configuração e que
o usuário não perca ajustes ao trocar de UI.

Localização: ao lado do executável quando congelado, senão na raiz do repo —
igual ao `getConfigDir()` do main.js.
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any

def ganho_db(valor) -> float:
    """Converte o valor de ganho salvo em dB numérico.

    Formatos que a config já teve nesta sessão:
      "" | "seguir o sistema (recomendado)" -> 0.0 (segue o mixer do Windows)
      "12"                                   -> 12.0
    O ERRO medido: a UI gravava o TEXTO da opção e o float() estourava com
    "could not convert string to float: 'seguir o sistema (recomendado)'".
    """
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


PADRAO: dict[str, Any] = {
    "idioma": "auto",
    "fps": "30",
    "videoBitrate": "2500",
    "audioBitrate": "192",
    "resolution": "source",
    "micGain": "",      # vazio = seguir o volume do sistema (volume 1.0)
    "sysGain": "",
    "closeBehavior": "tray",    # fechar = ir para a bandeja (pedido do usuário)
    "fechar_para_bandeja": True,
    "folder": "",   # vazio = Vídeos do usuário (resolvido na hora na UI)
    "shortcuts": {
        "start": "Control+Shift+R",
        "stop": "Control+Shift+S",
        "pause": "Control+Shift+P",
        "mute": "Control+Shift+M",
        "toggleAudio": "Control+Shift+A",
        "toggleWindow": "Control+Shift+H",
    },
    "rtmp": [],
    "scenes": [],
}


def caminho_config() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.ini"
    return Path(__file__).resolve().parent.parent / "config.ini"


def carregar() -> dict[str, Any]:
    """Lê o INI e devolve um dict plano no formato que a UI espera."""
    cfg = dict(PADRAO)
    cfg["shortcuts"] = dict(PADRAO["shortcuts"])
    p = caminho_config()
    if not p.exists():
        return cfg
    cp = configparser.ConfigParser()
    try:
        cp.read(p, encoding="utf-8")
    except Exception:
        return cfg

    if cp.has_section("geral"):
        if "idioma" in cp["geral"]:
            cfg["idioma"] = cp["geral"]["idioma"]
    if cp.has_section("recording"):
        for chave in ("fps", "videoBitrate", "audioBitrate", "resolution",
                      "micGain", "sysGain", "closeBehavior", "folder"):
            if chave in cp["recording"]:
                cfg[chave] = cp["recording"][chave]
    if cp.has_section("shortcuts"):
        for chave in cfg["shortcuts"]:
            if chave in cp["shortcuts"]:
                cfg["shortcuts"][chave] = cp["shortcuts"][chave]
    if cp.has_section("rtmp") and "destinos" in cp["rtmp"]:
        import json
        try:
            cfg["rtmp"] = json.loads(cp["rtmp"]["destinos"])
        except Exception:
            cfg["rtmp"] = []
    if cp.has_section("scenes") and "lista" in cp["scenes"]:
        import json
        try:
            cfg["scenes"] = json.loads(cp["scenes"]["lista"])
        except Exception:
            cfg["scenes"] = []
    return cfg


def salvar(cfg: dict[str, Any]) -> None:
    """Grava no mesmo INI, preservando as seções que o Electron usa."""
    import json

    cp = configparser.ConfigParser()
    p = caminho_config()
    if p.exists():
        try:
            cp.read(p, encoding="utf-8")
        except Exception:
            pass

    if not cp.has_section("geral"):
        cp.add_section("geral")
    cp["geral"]["idioma"] = str(cfg.get("idioma", "auto"))

    if not cp.has_section("shortcuts"):
        cp.add_section("shortcuts")
    for k, v in (cfg.get("shortcuts") or {}).items():
        cp["shortcuts"][k] = str(v)

    if not cp.has_section("recording"):
        cp.add_section("recording")
    for chave in ("fps", "videoBitrate", "audioBitrate", "resolution",
                  "micGain", "sysGain", "closeBehavior", "folder"):
        cp["recording"][chave] = str(cfg.get(chave, PADRAO.get(chave, "")))

    if not cp.has_section("rtmp"):
        cp.add_section("rtmp")
    cp["rtmp"]["destinos"] = json.dumps(cfg.get("rtmp") or [],
                                        ensure_ascii=False)

    if not cp.has_section("scenes"):
        cp.add_section("scenes")
    cp["scenes"]["lista"] = json.dumps(cfg.get("scenes") or [],
                                       ensure_ascii=False)

    with open(p, "w", encoding="utf-8") as fh:
        cp.write(fh)
