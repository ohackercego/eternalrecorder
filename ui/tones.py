"""Sons de estado da gravação — tons senoidais curtos, tocados de verdade.

HISTÓRICO (por que este arquivo foi e voltou)
=============================================
1. O app tocava `winsound.Beep` — a campainha do PC: onda quadrada, volume
   máximo, toca no MESMO dispositivo que está sendo gravado. O usuário pediu
   para tirar ("tira esse beep").
2. Depois disso o módulo foi zerado por completo (todas as funções no-op).
   Resultado medido agora: **nenhum som toca em nenhum evento** — o usuário
   relata exatamente isso, e a suspeita de "a IA implementou mas não toca" era
   correta pela metade: o arquivo estava no-op de propósito.
3. Ainda nesta revisão descobri por que implementações anteriores "não
   tocavam" mesmo com código: **`winsound` NÃO EXISTE no Python embarcado do
   app** (`python-embed` é uma build mínima, sem `_winsound`). ImportError
   engolido em `except Exception: pass` = silêncio absoluto, para sempre.

DECISÕES DESTA VERSÃO
=====================
- Síntese própria em numpy + `sounddevice` (presente no runtime: 0.5.6).
  Não depende de `winsound`, nem de arquivo .wav no disco, nem de `ffplay`.
- Onda SENOIDAL com envelope (fade in/out de 5 ms) — não é a campainha do
  BIOS: sem harmônicos duros, volume baixo (0.20), nada de estalo.
- Fallback em cascata: `sounddevice` -> `winmm.PlaySoundW` por ctypes (em
  memória, sem `winsound`) -> nada. Cada nível loga se funcionou, então "não
  toca" nunca mais é um mistério sem evidência.
- Reprodução em thread própria com fila: a UI nunca bloqueia.
- `aguardar()` existe para o painel esperar o tom terminar ANTES de a captura
  começar (senão o próprio bipe entra no arquivo).

CONTAMINAÇÃO DO ARQUIVO
=======================
Qualquer som sai pelo dispositivo padrão, e o `wasapi_output_capture` grava
justamente ele. Por isso o painel:
  - toca `inicio` e ESPERA antes de abrir a captura;
  - toca `pausa` DEPOIS de o output estar pausado (nada é escrito);
  - toca `retomada` e espera antes de despausar;
  - pausa o output na hora e só então toca `fim` no stop.
Este módulo só toca; a ordem é responsabilidade de quem chama.
"""
from __future__ import annotations

import io
import math
import queue
import struct
import threading

from engine.logs import logger

_log = logger("ui.tones")

ATIVO = True
VOLUME = 0.20           # 0..1 — baixo de propósito: é aviso, não mídia
TAXA = 48000

# Perfil de cada evento: (freq_hz, duração_ms) em sequência.
# Famílias com sentido auditivo: subir = começou/retomou, descer = parou/pausou.
PERFIS = {
    "inicio":    ((660, 70), (880, 90)),          # sobe  — começou
    "pausa":     ((520, 70), (360, 95)),          # desce — parou no meio
    "retomada":  ((360, 70), (520, 95)),          # sobe  — voltou
    "fim":       ((700, 70), (470, 100)),         # desce — encerrou
    "salvo":     ((880, 55), (1180, 55), (1180, 95)),
    "erro":      ((300, 120), (240, 170)),        # grave e lento
    "parada":    ((440, 90),),
    "encerrada": ((620, 80),),
}

LEGENDA = {
    "inicio": "Gravação iniciada",
    "pausa": "Gravação pausada",
    "retomada": "Gravação retomada",
    "fim": "Gravação encerrada",
    "salvo": "Arquivo salvo",
    "erro": "Erro na gravação",
}
ESTADOS = ("inicio", "pausa", "retomada", "fim", "salvo", "erro")

_fila = queue.Queue()
_worker = None
_ocupado = threading.Event()      # há tom tocando agora
_lock = threading.Lock()
_backend = "?"                    # qual caminho está funcionando
_backend_testado = False


# ───────────────────────────────────────────────────────────── síntese
def _amostras(perfil, volume=VOLUME):
    """Gera a sequência como array float32 mono (numpy)."""
    import numpy as np

    partes = []
    for freq, ms in perfil:
        n = max(1, int(TAXA * ms / 1000))
        t = np.arange(n, dtype=np.float64) / TAXA
        onda = np.sin(2.0 * math.pi * freq * t)
        # envelope: 5 ms de ataque e queda — sem estalo de chaveamento
        env = np.ones(n, dtype=np.float64)
        f = min(n // 2, max(1, int(TAXA * 0.005)))
        if f > 1:
            env[:f] = np.linspace(0.0, 1.0, f)
            env[-f:] = np.linspace(1.0, 0.0, f)
        partes.append(onda * env * float(volume))
        partes.append(np.zeros(int(TAXA * 0.010), dtype=np.float64))  # 10 ms
    return np.concatenate(partes).astype(np.float32)


def wav(nome):
    """O mesmo tom como WAV PCM 16-bit em memória (fallback e testes)."""
    import numpy as np

    perfil = PERFIS.get(nome)
    if not perfil:
        return b""
    arr = _amostras(perfil)
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    n = len(pcm)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + n))
    buf.write(b"WAVEfmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, TAXA, TAXA * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", n))
    buf.write(pcm)
    return buf.getvalue()


def sequencia(nome):
    """Perfil do evento (compatibilidade com chamadas antigas)."""
    return PERFIS.get(nome, ())


# ───────────────────────────────────────────────────────────── backend
def _tocar_sounddevice(pcm_bytes):
    import numpy as np
    import sounddevice as sd

    # reconstrói o array do WAV (mesma fonte que o fallback usa)
    dados = np.frombuffer(pcm_bytes[44:], dtype="<i2").astype(np.float32) / 32767.0
    sd.play(dados, TAXA, blocking=True)


def _tocar_winmm(pcm_bytes):
    """`PlaySoundW` do winmm por ctypes — sem `winsound`, que não existe aqui."""
    import ctypes

    winmm = ctypes.WinDLL("winmm")
    winmm.PlaySoundW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_uint]
    winmm.PlaySoundW.restype = ctypes.c_bool
    SND_MEMORY, SND_NODEFAULT = 0x0004, 0x0002
    buf = ctypes.create_string_buffer(pcm_bytes, len(pcm_bytes))
    ok = winmm.PlaySoundW(buf, None, SND_MEMORY | SND_NODEFAULT)
    if not ok:
        raise RuntimeError("PlaySoundW devolveu False")


def _detectar_backend():
    """Qual caminho de áudio funciona NESTE runtime. Loga o veredito uma vez.

    Antes nada era testado: `import winsound` falhava dentro de um try/except
    mudo e o app passava anos sem emitir som. Aqui a falha vira log.
    """
    global _backend, _backend_testado
    if _backend_testado:
        return _backend
    _backend_testado = True
    try:
        import sounddevice as sd
        _ = sd.query_devices(kind="output")
        _backend = "sounddevice"
        _log.info("tom: backend=sounddevice (PortAudio %s)",
                  getattr(sd, "__version__", "?"))
        return _backend
    except Exception as e:
        _log.warning("tom: sounddevice indisponível (%s: %s)",
                     type(e).__name__, e)
    try:
        _tocar_winmm(wav("parada"))
        _backend = "winmm"
        _log.info("tom: backend=winmm (PlaySoundW via ctypes)")
        return _backend
    except Exception as e:
        _log.error("tom: NENHUM backend de áudio disponível (%s: %s) — "
                   "o app vai rodar sem bipes", type(e).__name__, e)
    _backend = "nenhum"
    return _backend


def _loop():
    while True:
        pcm = _fila.get()
        if pcm is None:
            _fila.task_done()
            return
        _ocupado.set()
        try:
            if _backend == "sounddevice":
                _tocar_sounddevice(pcm)
            elif _backend == "winmm":
                _tocar_winmm(pcm)
        except Exception as e:
            _log.error("tom: falha ao tocar (%s: %s)", type(e).__name__, e)
        finally:
            _ocupado.clear()
            _fila.task_done()


def _garantir_worker():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True,
                                       name="tones")
            _worker.start()


def tocar(nome):
    """Enfileira o tom do evento. Nunca levanta exceção, nunca bloqueia."""
    if not ATIVO:
        return
    if nome not in PERFIS:
        _log.warning("tom: evento desconhecido %r", nome)
        return
    if _detectar_backend() == "nenhum":
        return
    pcm = wav(nome)
    if not pcm:
        return
    try:
        _garantir_worker()
        _fila.put(pcm)
    except Exception as e:
        _log.error("tom: não enfileirou %s (%s: %s)", nome,
                   type(e).__name__, e)


def aguardar(timeout=1.5):
    """Espera os tons enfileirados terminarem (para não entrar na captura)."""
    import time

    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if _fila.empty() and not _ocupado.is_set():
            return
        time.sleep(0.01)


def configurar(ativo=None, volume=None):
    global ATIVO, VOLUME
    if ativo is not None:
        ATIVO = bool(ativo)
    if volume is not None:
        try:
            VOLUME = max(0.0, min(1.0, float(volume)))
        except (TypeError, ValueError):
            pass
    _log.info("tom: ativo=%s volume=%.2f", ATIVO, VOLUME)


def status():
    """Diagnóstico (a tela de configurações pode mostrar isso)."""
    return {"ativo": ATIVO, "volume": VOLUME, "backend": _backend,
            "backend_testado": _backend_testado}


# ─────────────────────────────────────── API que a UI já chamava
def inicio():
    tocar("inicio")


def pausa():
    tocar("pausa")


def retomada():
    tocar("retomada")


def fim():
    tocar("fim")


def salvo():
    tocar("salvo")


def erro():
    tocar("erro")


def parada():
    tocar("parada")


def encerrada():
    tocar("encerrada")
