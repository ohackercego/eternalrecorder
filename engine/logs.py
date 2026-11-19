"""Logging central do Eternal Recorder.

PEDIDO DO USUÁRIO: "adicione logs para todas as funções na aplicação, todas
mesmo". Antes cada módulo fazia print() solto (ou nada) e os relatos de bug
chegavam sem evidência — não dava para saber nem qual caminho o app tomou.

DESIGN
======

- logging padrão do Python, um logger por módulo (nome do módulo no registro).
- Saída DUPLA: console (stderr) e ARQUIVO em %LOCALAPPDATA%/EternalRecorder/
  logs/er-AAAA-MM-DD.log — sobrevive a fechamento, é o que o usuário anexa no
  relatório.
- `logar` é o decorador: um @logar na função registra ENTRADA (com os
  argumentos) e SAÍDA (com o retorno resumido) e a exceção, se houver. É
  "todas as funções" sem encher o corpo delas de print.
- Custo: uma chamada de debug desligada é ~1 us. Ligado por padrão em INFO.

PRIVACIDADE
===========
Nada de conteúdo de gravação vai para o log — só caminhos, nomes de
dispositivo, tamanhos e contagens. Nenhuma chave de API (RTMP key sai
sempre redigida).
"""
from __future__ import annotations

import functools
import logging
import sys
import time
from pathlib import Path

NIVEL = logging.INFO

_formato = logging.Formatter(
    "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S")

_arquivo: Path | None = None


def _pasta_logs() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    p = base / "EternalRecorder" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


import os  # noqa: E402  (importado aqui para o docstring ficar no topo)

_arquivo = _pasta_logs() / time.strftime("er-%Y-%m-%d.log")

_arquivo_pai = logging.FileHandler(_arquivo, encoding="utf-8")
_arquivo_pai.setFormatter(_formato)

_console = logging.StreamHandler(sys.stderr)
_console.setFormatter(_formato)

_raiz = logging.getLogger("er")
_raiz.setLevel(NIVEL)
if not _raiz.handlers:
    _raiz.addHandler(_arquivo_pai)
    _raiz.addHandler(_console)


def logger(nome: str) -> logging.Logger:
    """Logger filho: er.motor, er.ui.gravacao, ..."""
    return _raiz.getChild(nome)


def _resumo(v) -> str:
    """Retorno resumido para o log: sem conteúdo, só tipo e tamanho."""
    if v is None:
        return "None"
    if isinstance(v, dict):
        return f"dict({len(v)} chaves)"
    if isinstance(v, (list, tuple)):
        return f"{type(v).__name__}({len(v)})"
    if isinstance(v, str) and len(v) > 80:
        return f"str({len(v)} chars)"
    return repr(v)[:80]


def logar(fn):
    """Decorador: registra entrada, saída e exceção da função.

    Aplicar em TODAS as funções públicas dos módulos foi o pedido. O nível de
    saída é DEBUG (não polui o INFO), a ENTRADA também DEBUG, e ERROS sobem
    como ERROR com traceback — é o que resolve relato sem evidência.
    """
    log = logger(fn.__module__.split(".")[-1])

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        args_txt = ", ".join(
            [_resumo(a) for a in args[1:]] +          # pula self
            [f"{k}={_resumo(v)}" for k, v in kwargs.items()])
        log.debug("→ %s(%s)", fn.__name__, args_txt[:160])
        t0 = time.perf_counter()
        try:
            r = fn(*args, **kwargs)
            log.debug("← %s [%d ms] %s", fn.__name__,
                      (time.perf_counter() - t0) * 1000, _resumo(r))
            return r
        except Exception as e:
            log.exception("✗ %s: %s: %s", fn.__name__,
                          type(e).__name__, e)
            raise

    return wrapped


def evento(modulo: str, mensagem: str, *args) -> None:
    """Log pontual INFO (o que o usuário precisa ver na trilha)."""
    logger(modulo).info(mensagem, *args)


def caminho_log() -> Path:
    return _arquivo
