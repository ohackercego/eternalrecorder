"""Motor de captura em libobs (pylibobs) — cenas, composição, RTMP.

## Por que libobs e não capturekit

Medido nesta máquina, e a comparação é decisiva:

    capturekit 0.1.0            pylibobs (libobs / OBS 32)
    ───────────────────────     ─────────────────────────────
    monitor e janela            monitor, janela, jogo, câmera, tela cheia
    SEM câmera                  dshow_input
    SEM composição              N fontes por cena, com posição/escala/crop
    SEM RTMP                    rtmp_output + rtmp_common/rtmp_custom
    áudio por processo          wasapi_process_output_capture
    (gate de build 20348)       (nativo, sem gate)

O libobs é o núcleo do OBS Studio, mantido há mais de uma década. Toda fonte
que o OBS usa está aqui, com o mesmo comportamento.

## Modelo

Um `OBSContext` global (libobs é singleton). Dentro dele:

    Cena  = Scene.create(nome)
    Fonte = Source.create(kind, nome, settings)   +  cena.add(fonte)
    Item  = o que a cena devolve; posição/escala/visibilidade ficam nele
    Saída = Output.create("ffmpeg_muxer"|"rtmp_output", ...)

O programa (o que vai para a saída) é uma cena: `set_current_scene`. Trocar de
cena durante a gravação muda o que sai, sem reiniciar o arquivo — é a troca ao
vivo que o painel de Cenas pede.

## Áudio

Cada fonte com áudio é uma trilha. `AudioEncoder` com `mixer` decide o que vai
para a saída. Fontes:

    wasapi_output_capture          desktop inteiro
    wasapi_input_capture           microfone
    wasapi_process_output_capture  um processo (janela específica)

Isso elimina o monkeypatch do gate de build que o capturekit exigia.
"""
from __future__ import annotations

import threading
import time

from .logs import logger, evento as _ev
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# kinds reais do libobs, confirmados por enum_input_types() nesta máquina
FONTE_MONITOR = "monitor_capture"
FONTE_JANELA = "window_capture"
FONTE_JOGO = "game_capture"
FONTE_CAMERA = "dshow_input"
FONTE_AUDIO_SISTEMA = "wasapi_output_capture"
FONTE_AUDIO_MIC = "wasapi_input_capture"
FONTE_AUDIO_PROCESSO = "wasapi_process_output_capture"

FORMATOS_VIDEO = {"mp4": "mp4", "mkv": "mkv", "mov": "mov", "flv": "flv"}
FORMATOS_AUDIO = {"mp3": "mp3", "wav": "wav", "flac": "flac", "m4a": "m4a"}


@dataclass
class Opcoes:
    modo: str = "monitor"          # monitor | janela | camera | audio
    fps: int = 30
    resolucao: Optional[tuple[int, int]] = None
    bitrate_v: int = 0             # kbps; 0 = CRF
    bitrate_a: int = 192
    audio: str = "both"            # none | mic | system | app | both
    monitor: int = 0
    janela_hwnd: Optional[int] = None
    pid_alvo: Optional[int] = None
    camera: Optional[str] = None
    ganho_mic_db: float = 12.0
    ganho_sys_db: float = 6.0
    mic_indice: Optional[int] = None
    saida: str = ""
    formato: str = "mp4"
    # fonte sobreposta (modo normal): câmera no canto
    camera_sobreposta: bool = False
    camera_sobreposta_nome: Optional[str] = None
    camera_canto: str = "sup-dir"      # sup-esq | sup-dir | inf-esq | inf-dir
    camera_tamanho: float = 0.28       # fração da largura do canvas
    camera_borda: str = "solida"       # solida | gradiente | neon | nenhuma
    # cenas: lista de {"nome": str, "fontes": [...]} para o painel de Cenas
    cena_inicial: Optional[str] = None


@dataclass
class Sessao:
    opcoes: Opcoes
    inicio: float = 0.0
    cena: object = None
    saida: object = None
    fontes: list = field(default_factory=list)
    # Objetos Python (Source e SceneItem) das fontes vivas.
    # SEM ISTO A GRAVAÇÃO SAI PRETA: medido, ao deixar o wrapper sair de
    # escopo o __del__ do pylibobs chama obs_source_release, a fonte para de
    # entregar quadro e a cena continua "com item" mas sem dados —
    # 75 frames, todos YAVG=16. Com a referência viva: 75 frames, 1 preto
    # (só o primeiro, o do aquecimento do WGC).
    objetos: list = field(default_factory=list)
    erro: Optional[str] = None
    aviso: Optional[str] = None
    frames: int = 0
    rtmp_urls: list = field(default_factory=list)
    pausado: bool = False
    # taxa de áudio efetiva da sessão (casada com o dispositivo) — o encoder
    # e o remux precisam declarar a MESMA, senão volta a reamostrar
    taxa_audio: int = 48000
    # itens de VÍDEO da cena — o que a troca de cena remove/repoõ. Fontes de
    # áudio ficam de fora: trocar a imagem não pode derrubar o som.
    itens_video: list = field(default_factory=list)
    # fontes de ÁUDIO vivas — a troca de cena ao vivo aplica mute/unmute nelas
    fontes_vivas: list = field(default_factory=list)
    # tempo TOTAL já passado em pausa (segundos). O cronômetro da UI desconta
    # isto — antes ele fazia monotonic() - inicio e os segundos continuavam
    # andando com a gravação parada.
    tempo_pausado: float = 0.0
    # instante (monotonic) em que a pausa ATUAL começou; 0 = não pausado
    pausa_desde: float = 0.0

    def decorrido(self) -> float:
        """Tempo GRAVADO (sem contar pausas).

        Pausado, devolve o tempo congelado no instante da pausa; rodando,
        devolve o tempo real menos tudo o que já ficou em pausa.
        """
        if not self.inicio:
            return 0.0
        agora = self.pausa_desde if self.pausa_desde else time.monotonic()
        return max(0.0, agora - self.inicio - self.tempo_pausado)

    @property
    def trilhas_audio(self) -> int:
        """Quantas fontes de áudio entraram na cena (a UI anuncia isso)."""
        nomes = {"Microfone", "Áudio sistema", "Áudio app"}
        n = 0
        for d in self.fontes:
            if (d.get("kind", "").startswith("wasapi") or
                    d.get("nome") in nomes):
                n += 1
        return n

    @property
    def caminho(self) -> str:
        """Arquivo que está sendo gravado (a UI usa para 'abrir pasta')."""
        return self.opcoes.saida


class Motor:
    """Fachada do libobs. A UI só chama estes métodos."""

    def __init__(self) -> None:
        self._lock_cena = threading.RLock()
        self._ctx = None
        self._disponivel = False
        self._motivo = ""
        self._lock = threading.Lock()
        self._refs: list = []      # fontes/itens vivos (ver Sessao.objetos)
        self._cena_programa = None
        self._sessao_ativa = None
        self.capabilities: dict = {}
        self._tipos_fonte: list[str] = []
        self._carregar()

    # ------------------------------------------------------------------ setup
    def _instalar_handler_de_ui(self) -> None:
        """Registra o handler de tarefas de UI do libobs.

        BUG que isto corrige (log do usuário, 2.3.0):

            error: UI task could not be queued, there's no UI task handler!  (x6)

        O libobs agenda `obs_queue_task(OBS_TASK_UI, ...)` quando uma fonte
        difere a destruição do recurso de GPU para a thread de UI — e, sem
        handler registrado, a tarefa é **descartada**: o destroy nunca roda, o
        recurso vaza e o erro aparece uma vez por fonte no fim de cada gravação.

        Este host não tem laço de UI do libobs (quem tem é o frontend Qt do
        OBS), então o handler executa a tarefa na hora. O objeto do callback
        precisa ficar vivo em `self` — se o cffi coletar o handler, o libobs
        chama um ponteiro morto e o processo cai.
        """
        try:
            from pylibobs import _ffi
            ffi = _ffi.ffi
            lib = _ffi.get_lib()
        except Exception as e:
            logger("motor").warning("UI task handler: pylibobs indisponível "
                                    "(%s: %s)", type(e).__name__, e)
            return
        if getattr(self, "_ui_task_handler", None) is not None:
            return
        contador = {"executadas": 0, "descartadas": 0}

        @ffi.callback("void(void(*)(void *), void *, _Bool)")
        def _handler(task, param, wait):
            if task == ffi.NULL:
                contador["descartadas"] += 1
                return
            try:
                task(param)
                contador["executadas"] += 1
            except Exception:
                contador["descartadas"] += 1

        self._ui_task_handler = _handler        # mantém o cffi vivo
        self._ui_task_stats = contador
        try:
            lib.obs_set_ui_task_handler(_handler)
            logger("motor").info("UI task handler registrado")
        except Exception as e:
            logger("motor").warning("UI task handler: não registrou "
                                    "(%s: %s)", type(e).__name__, e)

    def _carregar(self) -> None:
        try:
            from pylibobs import OBSContext
            self._ctx = OBSContext()
            self._ctx.__enter__()
            # ANTES de qualquer fonte: sem handler, todo destroy diferido é
            # descartado e o log enche de "UI task could not be queued"
            self._instalar_handler_de_ui()
            self._ctx.set_video(width=1920, height=1080, fps_num=30)
            # ── TAXA DE ÁUDIO: 48000, NÃO o padrão 44100 ──
            # `set_audio()` sem argumento usa 44100, mas os dispositivos WASAPI
            # do Windows entregam 48000. Medido: com 44100 o arquivo de 6 s
            # saía com 6,01 s de duração porém o áudio repetia e travava — o
            # libobs reamostrava cada bloco de 48k para 44.1k e o buffer
            # acumulava. 48000 é a taxa nativa do WASAPI e do AAC aqui.
            self._ctx.set_audio(samples_per_sec=48000)
            try:
                self._ctx.load_modules()
            except Exception:
                pass
            self._disponivel = True
            self.capabilities = {"resumo": "libobs (OBS) ativo"}
            from pylibobs import enum_input_types
            for t in enum_input_types():
                nome = t[0] if isinstance(t, (tuple, list)) else str(t)
                self._tipos_fonte.append(nome)
        except Exception as e:
            self._motivo = f"{type(e).__name__}: {e}"
            self._disponivel = False
            self._ctx = None

    @property
    def disponivel(self) -> bool:
        return self._disponivel

    @property
    def motivo(self) -> str:
        return self._motivo

    @property
    def tipos_fonte(self) -> list[str]:
        return list(self._tipos_fonte)

    def encerrar(self) -> None:
        """Fecha o libobs. Chamado ao sair do app."""
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._ctx = None
            self._disponivel = False

    # --------------------------------------------------------- descoberta
    def monitores(self) -> list[dict]:
        """Monitores do sistema (libobs não lista; usa a API do Windows)."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD),
                        ("szDevice", wintypes.WCHAR * 32)]

        saida = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                            wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                            wintypes.LPARAM)
        def _cb(hmon, _hdc, _rect, _lp):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                saida.append({
                    "indice": len(saida),
                    "nome": info.szDevice,
                    "largura": info.rcMonitor.right - info.rcMonitor.left,
                    "altura": info.rcMonitor.bottom - info.rcMonitor.top,
                    "principal": bool(info.dwFlags & 1),
                })
            return True

        user32.EnumDisplayMonitors(None, None, _cb, 0)
        return saida or [{"indice": 0, "nome": "Monitor principal",
                          "largura": 1920, "altura": 1080, "principal": True}]

    def janelas(self) -> list[dict]:
        """Janelas capturáveis, com hwnd — o `window_capture` usa hwnd."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        saida: list[dict] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n < 2:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            titulo = buf.value.strip()
            if len(titulo) < 2:
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            larg = rect.right - rect.left
            alt = rect.bottom - rect.top
            if larg < 60 or alt < 40:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            saida.append({"hwnd": int(hwnd), "titulo": titulo,
                          "pid": int(pid.value),
                          "largura": larg, "altura": alt})
            return True

        user32.EnumWindows(_cb, 0)
        return saida

    def cameras(self) -> list[dict]:
        """Câmeras via dshow (enumeração do próprio OBS)."""
        from pylibobs import Source, get_source_defaults
        saida: list[dict] = []
        try:
            # o source dshow lista os dispositivos nas propriedades; aqui basta
            # confirmar que o tipo existe e devolver o que o Windows expõe
            import subprocess
            import sys as _sys
            flags = 0x08000000 if _sys.platform == "win32" else 0
            si = None
            if _sys.platform == "win32":
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-list_devices", "true",
                 "-f", "dshow", "-i", "dummy"],
                capture_output=True, text=True, timeout=15,
                creationflags=flags, startupinfo=si)
            for linha in r.stderr.splitlines():
                if "(video)" in linha and '"' in linha:
                    nome = linha.split('"')[1]
                    if nome and nome not in [c["nome"] for c in saida]:
                        saida.append({"nome": nome})
        except Exception:
            pass
        return saida

    def microfones(self) -> list[dict]:
        """Microfones (wasapi_input_capture pega o padrão; lista é informativa)."""
        import sounddevice as sd
        saida = []
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    saida.append({"indice": i, "nome": d["name"],
                                  "padrao": i == sd.default.device[0]})
        except Exception:
            pass
        return saida

    def dispositivos_audio(self) -> list[dict]:
        """Dispositivos de saída (para wasapi_output_capture)."""
        import sounddevice as sd
        saida = []
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0:
                    saida.append({"indice": i, "nome": d["name"],
                                  "padrao": i == sd.default.device[1]})
        except Exception:
            pass
        return saida

    # ----------------------------------------------------------- cenas
    def criar_cena(self, nome: str, fontes: Optional[list[dict]] = None):
        """Cria uma cena e adiciona as fontes descritas."""
        from pylibobs import Scene
        cena = Scene.create(nome)
        for desc in (fontes or []):
            try:
                self._adicionar_fonte(cena, desc)
            except Exception as e:
                print(f"[motor] fonte {desc} falhou: {e}")
        self._refs.append(cena)
        return cena

    def cena_atual(self):
        """A cena que está no programa (o que grava)."""
        from pylibobs import Scene
        try:
            return Scene.from_source(
                __import__("pylibobs").scene.get_current_scene())
        except Exception:
            return None

    def definir_cena(self, cena) -> None:
        """Põe a cena no canal 0 do programa — o que vai para a saída.

        `obs_set_output_source(0, source)`. Sem isso a saída grava TELA PRETA:
        medido, o arquivo ficava em 0 bytes durante toda a gravação e saía com
        12 KB de 4 s. Com a cena no programa: 2,2 MB nos mesmos 4 s.

        `pylibobs.scene` não tem `set_current_scene` (o módulo só expõe
        create/from_source), então usa o binding direto. O ponteiro é `_ptr`.
        """
        from pylibobs import _ffi
        lib = _ffi.get_lib()
        src = cena.as_source() if hasattr(cena, "as_source") else cena
        ptr = getattr(src, "_ptr", None)
        if ptr is None:
            raise RuntimeError("source sem _ptr: não foi possível pôr no programa")
        lib.obs_set_output_source(0, ptr)
        # guarda a referência ANTES de qualquer coisa: sem ela o wrapper é
        # coletado, o __del__ chama obs_source_release e a saída grava preto.
        self._cena_programa = cena
        # ── ONDE guardar ──
        # Se há sessão ativa (chamada dentro de iniciar ou numa troca ao vivo),
        # a cena vai para sessao.objetos, que o parar() libera. Antes eu
        # anexava sempre em self._refs — e como iniciar() já tinha transferido
        # _refs para a sessão, a cena ficava órfã em _refs até o encerrar().
        # Medido: 7 cenas de sessão acumuladas num teste de 7 gravações.
        if self._sessao_ativa is not None:
            self._sessao_ativa.objetos.append(cena)
        else:
            self._refs.append(cena)

    def adicionar_fonte(self, cena, desc: dict):
        return self._adicionar_fonte(cena, desc)

    def _adicionar_fonte(self, cena, desc: dict):
        """Cria a fonte e devolve o item de cena (para pos/scale)."""
        from pylibobs import Source
        kind = desc.get("kind") or desc.get("tipo")
        if not kind:
            raise ValueError("fonte sem 'kind'")
        nome = desc.get("nome") or kind
        settings = desc.get("settings") or {}

        # ── tradução para os campos que o libobs REALMENTE lê ──
        # Descobertos inspecionando get_properties() de cada fonte. Mandar
        # "monitor": 0 (número) deixava a fonte com display vazio e o libobs
        # gravava 4 KB/s de tela preta — foi o bug do teste anterior.
        if kind == FONTE_MONITOR:
            monitor_id = desc.get("monitor_id")
            if not monitor_id:
                monitor_id = self._monitor_id(int(desc.get("monitor", 0)))
            if monitor_id:
                settings["monitor_id"] = monitor_id
            settings.setdefault("method", 2)          # 2 = Modern (WGC)
            settings.setdefault("capture_cursor", True)
        elif kind == FONTE_JANELA:
            alvo = desc.get("janela_id") or desc.get("window")
            if not alvo and desc.get("hwnd"):
                alvo = self._janela_id(int(desc["hwnd"]))
            if alvo:
                settings["window"] = alvo
                # LOG DO ID: sem isto, uma captura preta nao diz se o id foi
                # montado errado ou se o plugin nao achou a janela. O log do
                # libobs mostra `executable`/`class` mas NAO mostra o titulo
                # que mandamos (ele reformata), entao a unica prova de que o
                # id saiu completo e' esta linha.
                logger("motor").info("window id enviado: %r", alvo)
            # `method` 2 = WGC (Windows Graphics Capture). MEDIDO: WGC captura
            # a janela mesmo quando ela esta' coberta por outra ou sem foco.
            # BitBlt (1) devolve PRETO nesses casos e com janelas aceleradas
            # por GPU. Automatic (0) escolhe BitBlt em varios casos e tambem
            # sai preto — por isso vai o numero 2 fixo, nao "Automatic".
            #
            # ATENCAO: a janela MINIMIZADA sai preta em QUALQUER metodo
            # (medido: YAVG=16 com WGC). Nao ha' como contornar isso na
            # fonte; o aviso ao usuario fica em `_janela_minimizada()`.
            settings.setdefault("method", 2)
            settings.setdefault("priority", 1)
            # o setting do cursor chama-se `cursor` no win-capture (o nome
            # `capture_cursor` e' de OUTRAS fontes e aqui e' ignorado —
            # medido em get_properties()).
            settings.setdefault("cursor", True)
            settings.setdefault("client_area", False)
        elif kind == FONTE_CAMERA:
            cam = desc.get("camera")
            if cam:
                settings["video_device_id"] = self._camera_id(cam)
            settings.setdefault("res_type", 0)        # 0 = padrão do dispositivo
            settings.setdefault("buffering", 2)       # 2 = desativar
        elif kind in (FONTE_AUDIO_MIC, FONTE_AUDIO_SISTEMA):
            _log = logger("motor")
            _log.info("fonte de áudio %s (%s): ganho_db=%s",
                      nome, kind, desc.get("ganho_db", 0))
            # ── RELÓGIO DO DISPOSITIVO ──
            # MEDIDO (sinal de 1 bipe/s, 14 s de gravação):
            #   use_device_timing padrão (liga)  -> 11 bipes, razão 1,387
            #   use_device_timing False          -> 21 bipes, razão 0,697
            # Ou seja: desligar PIORA. O padrão é o menos ruim, e o problema
            # real não está aqui.
            #
            # A causa é o descompasso de taxa: o dispositivo roda a 44100 Hz
            # e o contexto a 48000. O libobs reamostra, e nesta máquina a
            # reamostragem acumula erro — o áudio derivá e o muxer repete
            # amostras para manter o alinhamento.
            #
            # O caminho correto é casar a taxa do CONTEXTO com a do
            # dispositivo (ver `iniciar()`: `_taxa_nativa()`), em vez de
            # forçar 48000 sempre.
            settings.setdefault("device_id", desc.get("device_id", "default"))

        elif kind == FONTE_AUDIO_PROCESSO:
            pid = desc.get("pid")
            if pid:
                # ── FORMATO DO SETTING `window` ──
                # BUG MEDIDO: eu mandava "pid:exe" (dois campos). O libobs faz
                # `strlist_split(str, ':', true)` e exige strlist[0], [1] E [2]
                # (libobs/util/windows/window-helpers.c, ms_build_window_strings).
                # Com dois campos, strlist[2] é NULL e ele retorna com title,
                # class e exe todos vazios — a fonte então chama
                # ms_find_window() com string vazia e falha com
                # `[[VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK]] Failed to find
                # window`, repetindo `Device invalidated. Retrying` para sempre.
                # Resultado: trilha de áudio existe no arquivo, com silêncio.
                #
                # O formato correto é "title:class:exe", com escape
                # '#' -> "#22" e ':' -> "#3A" (encode_dstr, nessa ordem).
                hwnd = desc.get("hwnd")
                janela = None
                if hwnd:
                    janela = self._janela_id(int(hwnd))
                if not janela:
                    janela = self._janela_do_pid(int(pid))
                if janela:
                    settings["window"] = janela
                settings.setdefault("priority", 1)

        fonte = Source.create(kind, nome, settings)
        item = cena.add(fonte)
        # guarda ANTES de qualquer outra coisa: se o wrapper morrer aqui, a
        # fonte para de capturar (ver comentário em Sessao.objetos)
        if self._refs is not None:
            self._refs.append(fonte)
            if item is not None:
                self._refs.append(item)
        # fonte de ÁUDIO vai para a sessão: a troca de cena ao vivo muda o
        # mute delas (cena manda no áudio)
        if kind in (FONTE_AUDIO_MIC, FONTE_AUDIO_SISTEMA, FONTE_AUDIO_PROCESSO):
            if self._sessao_ativa is not None:
                self._sessao_ativa.fontes_vivas.append(fonte)
                logger("motor").info(
                    "fonte de áudio %s registrada na sessão (mute ao vivo ok)",
                    nome)

        # ── GANHO OPCIONAL ──
        # volume=1.0 é o que o sistema entrega (o usuário ajusta pelo mixer
        # do Windows). Só multiplica se o usuário PEDIR ganho na config —
        # antes o ganho fixo de 12/6 dB LIMITAVA o áudio de quem já ajustava
        # o volume no sistema (relatado). db -> linear: 10^(db/20).
        try:
            ganho = float(desc.get("ganho_db", 0) or 0)
        except Exception:
            ganho = 0.0
        _log = logger("motor")
        if ganho and fonte is not None:
            try:
                fonte.volume = min(4.0, 10 ** (ganho / 20.0))
                _log.info("ganho aplicado na fonte %s: +%.0f dB -> volume %.2f",
                          nome, ganho, fonte.volume)
            except Exception as e:
                _log.error("ganho falhou na fonte %s: %s", nome, e)
        else:
            _log.info("fonte %s: volume 1.0 (segue o sistema, ganho db=%s)",
                      nome, ganho)
        # MUTE INICIAL (cena): a cena escolhe qual fonte nasce audível
        if desc.get("mutado") and fonte is not None:
            try:
                fonte.muted = True
                _log.info("fonte %s nasce MUTADA (cena não pede este áudio)",
                          nome)
            except Exception as e:
                _log.error("mute inicial falhou em %s: %s", nome, e)

        # posição/escala: câmera sobreposta vai no canto, pequena
        if desc.get("sobreposta") and item is not None:
            self._posicionar_sobreposta(item, desc)
        if desc.get("escala") and item is not None:
            try:
                tr = item.get_transform()
                tr.scale = tuple(desc["escala"])
                item.set_transform(tr)
            except Exception:
                pass
        return item

    def _taxa_audio_nativa(self) -> int:
        """Taxa que o dispositivo de áudio realmente entrega AO LIBOBS.

        MEDIDO nesta máquina (2026-11-21, log do app):

            sounddevice  query_devices(kind='output') -> 44100   (host MME)
            mesmo dispositivo no host WASAPI          -> 48000

        `query_devices(kind=...)` devolve o dispositivo padrão do host de MAIOR
        prioridade do PortAudio, que no Windows é o **MME** — e o MME reporta
        44100. O libobs NÃO usa MME: as fontes `wasapi_output_capture` e
        `wasapi_input_capture` abrem o dispositivo pelo **WASAPI**, a 48000. O
        código antigo lia a taxa do MME e configurava o contexto em 44100 com o
        dispositivo entregando 48000 — o libobs reamostrava cada bloco e o
        buffer acumulava (voz "fininha, cortando e repetindo").

        A prova está no próprio log do libobs, na mesma sessão:

            info: audio settings reset:  samples per sec: 44100   <- errado
            info: WASAPI: Device 'Fones...' [48000 Hz] initialized  <- real

        Correção: procurar o dispositivo pelo NOME dentro do host WASAPI e usar
        a taxa DELE. Só cai no palpite (48000) se o WASAPI não estiver listado.
        """
        try:
            import sounddevice as sd

            quer_entrada = self._usar_mic()
            hosts = list(sd.query_hostapis())
            aparelhos = list(sd.query_devices())

            def _taxa_wasapi() -> int:
                # 1. tenta o host WASAPI e o dispositivo padrão DELE
                for i, h in enumerate(hosts):
                    if "wasapi" not in str(h.get("name", "")).lower():
                        continue
                    chave = ("default_input_device" if quer_entrada
                             else "default_output_device")
                    alvo = h.get(chave, -1)
                    if isinstance(alvo, int) and 0 <= alvo < len(aparelhos):
                        taxa = int(aparelhos[alvo].get("default_samplerate") or 0)
                        if taxa:
                            return taxa
                # 2. o padrão do host apontou para índice inválido (-1): procura
                #    pelo NOME do dispositivo padrão do sistema dentro do WASAPI
                try:
                    nome_padrao = str(
                        sd.query_devices(kind="input" if quer_entrada
                                         else "output").get("name", ""))
                except Exception:
                    nome_padrao = ""
                canal = "max_input_channels" if quer_entrada else "max_output_channels"
                for i, d in enumerate(aparelhos):
                    if not d.get(canal):
                        continue
                    ha = hosts[d["hostapi"]].get("name", "") if d.get("hostapi") is not None else ""
                    if "wasapi" not in str(ha).lower():
                        continue
                    if nome_padrao and str(d.get("name", "")) == nome_padrao:
                        taxa = int(d.get("default_samplerate") or 0)
                        if taxa:
                            return taxa
                return 0

            taxa = _taxa_wasapi()
            if taxa in (44100, 48000, 88200, 96000, 176400, 192000):
                logger("motor").info(
                    "taxa de áudio: %d Hz (do host WASAPI; MME dizia %s)",
                    taxa, self._taxa_mme(quer_entrada))
                return taxa
        except Exception as e:
            logger("motor").warning("taxa de áudio: não deu para consultar "
                                    "(%s: %s)", type(e).__name__, e)
        # O libobs abre tudo por WASAPI no Windows; 48000 é a taxa nativa dele.
        return 48000

    @staticmethod
    def _taxa_mme(entrada: bool) -> str:
        """Só para o log: o que o host MME reporta (a fonte do bug)."""
        try:
            import sounddevice as sd
            return int(sd.query_devices(kind="input" if entrada
                                        else "output").get("default_samplerate"))
        except Exception:
            return "?"

    def _usar_mic(self) -> bool:
        o = getattr(self, "_opcoes_ativas", None)
        return bool(o is not None and o.audio in ("mic", "both"))

    @staticmethod
    def janela_minimizada(hwnd: int) -> bool:
        """A janela esta' indisponivel para captura? (gravar assim sai PRETO)

        MEDIDO com o Posty (Chrome) no mesmo harness:
            primeiro plano   YAVG=70.7  ok
            atras de outra   YAVG=70.7  ok
            MINIMIZADA       YAVG=16.0  PRETO

        E, mais importante, o caso que nao e' minimizacao: o Windows
        COMPOSITA janelas fora da tela atual e as marca como "cloaked" no
        DWM. Elas continuam `IsWindowVisible=True` e `IsIconic=False`, mas o
        WGC recebe um quadro PRETO.

        Medido nas janelas do Chrome desta maquina:
            hwnd=6293044  cloaked=2  <- "Nova guia", captura PRETA
            hwnd=4260142  cloaked=0  <- "Posty",     captura ok

        DWMWA_CLOAKED = 14. Valores: 0 = visivel; 1 = cloaked pelo app (outro
        desktop virtual); 2 = cloaked pelo sistema (fora do monitor atual ou
        janela "fantasma" do Chrome).
        """
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            h = int(hwnd)
            if u.IsIconic(h):
                return True
            dwm = ctypes.windll.dwmapi
            cloaked = ctypes.c_int(0)
            hr = dwm.DwmGetWindowAttribute(
                wintypes.HWND(h), 14, ctypes.byref(cloaked),
                ctypes.sizeof(cloaked))
            # 0x00000000 = S_OK. Se falhar, nao afirmamos nada.
            if hr == 0 and cloaked.value != 0:
                return True
            # janela "nao visivel" tambem sai preta
            if not u.IsWindowVisible(h):
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def motivo_preto(hwnd: int) -> str:
        """Texto do aviso quando a janela vai gravar preta (vazio se ok)."""
        try:
            import ctypes
            u = ctypes.windll.user32
            dwm = ctypes.windll.dwmapi
            h = int(hwnd)
            if u.IsIconic(h):
                return ("A janela está minimizada — a gravação vai sair preta. "
                        "Restaure a janela antes de gravar.")
            cloaked = ctypes.c_int(0)
            hr = dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)
            if hr == 0 and cloaked.value != 0:
                return ("Esta janela não está sendo desenhada pelo Windows "
                        "(fora do monitor atual ou em outro desktop) — a "
                        "gravação vai sair preta. Traga a janela para a tela "
                        "antes de gravar.")
            if not u.IsWindowVisible(h):
                return ("A janela está oculta — a gravação vai sair preta. "
                        "Mostre a janela antes de gravar.")
            return ""
        except Exception:
            return ""

    def _resolucao_nativa(self, o: Opcoes) -> tuple[int, int]:
        """Resolução do alvo quando o usuário escolhe "fonte"."""
        try:
            if o.modo == "monitor":
                mons = self.monitores()
                if 0 <= o.monitor < len(mons):
                    m = mons[o.monitor]
                    return int(m["largura"]), int(m["altura"])
            elif o.modo == "janela" and o.janela_hwnd:
                for j in self.janelas():
                    if j["hwnd"] == int(o.janela_hwnd):
                        # largura/altura par: H.264 4:2:0 exige múltiplo de 2
                        return (int(j["largura"]) // 2 * 2,
                                int(j["altura"]) // 2 * 2)
            elif o.modo == "camera":
                return 1280, 720
        except Exception:
            pass
        return 1920, 1080

    # ------------------------------------- câmera sobreposta
    def _dimensoes_canvas(self) -> tuple[int, int]:
        """Resolução base do vídeo configurado no contexto."""
        try:
            from pylibobs import _ffi
            lib = _ffi.get_lib()
            w = int(lib.obs_frontend_get_current_video_width()) \
                if hasattr(lib, "obs_frontend_get_current_video_width") else 0
            h = int(lib.obs_frontend_get_current_video_height()) \
                if hasattr(lib, "obs_frontend_get_current_video_height") else 0
            if w and h:
                return w, h
        except Exception:
            pass
        return getattr(self, "_canvas", (1920, 1080))

    def _posicionar_sobreposta(self, item, desc: dict) -> None:
        """Põe a webcam no canto pedido, com o tamanho pedido.

        A câmera é escalada por LARGURA (proporção preservada pela fonte) e
        encostada na margem do canvas com um respiro de 2%.

        Ordem de chamadas importa: `get_transform()` devolve pos/scale/rot e
        `set_transform()` reescreve o item inteiro — mexer só em `pos` depois
        de `scale` desfaz a escala.
        """
        try:
            from pylibobs import TransformInfo
            cw, ch = self._dimensoes_canvas()
            fracao = float(desc.get("tamanho") or 0.28)
            fracao = max(0.10, min(0.50, fracao))

            # tamanho da fonte (webcam costuma ser 4:3 ou 16:9)
            sw = sh = 0
            try:
                src = item.source if hasattr(item, "source") else item
                sw, sh = int(src.get_width() or 0), int(src.get_height() or 0)
                from pylibobs import _ffi
                lib = _ffi.get_lib()
                src_ptr = getattr(src, "_ptr", None)
                if src_ptr is not None and (not sw or not sh):
                    sw = int(lib.obs_source_get_width(src_ptr) or 0)
                    sh = int(lib.obs_source_get_height(src_ptr) or 0)
            except Exception:
                pass
            if not sw or not sh:
                sw, sh = 1280, 720

            alvo_w = cw * fracao
            escala = alvo_w / sw
            alvo_h = sh * escala

            margem = cw * 0.02
            canto = desc.get("canto") or "sup-dir"
            if canto == "sup-esq":
                x, y = margem, margem
            elif canto == "inf-esq":
                x, y = margem, ch - alvo_h - margem
            elif canto == "inf-dir":
                x, y = cw - alvo_w - margem, ch - alvo_h - margem
            else:                                    # sup-dir
                x, y = cw - alvo_w - margem, margem

            tr = item.get_transform()
            tr.pos = (float(x), float(y))
            tr.scale = (float(escala), float(escala))
            item.set_transform(tr)
            self._ultima_sobreposta = {
                "canvas": (cw, ch), "fonte": (sw, sh),
                "pos": (round(x), round(y)),
                "tamanho": (round(alvo_w), round(alvo_h)),
                "escala": round(escala, 4), "canto": canto,
            }
        except Exception as e:
            self._ultima_sobreposta = {"erro": f"{type(e).__name__}: {e}"}

    # ------------------------------------- IDs que o libobs aceita
    def _monitor_id(self, indice: int) -> str:
        """Device path do monitor (o libobs não aceita índice numérico)."""
        try:
            from pylibobs import Source
            s = Source.create(FONTE_MONITOR, "_probe_mon", {})
            props = s.get_properties()
            itens = []
            for p in props:
                if p.name == "monitor_id":
                    itens = [i for i in p.items if not i.disabled]
                    break
            s.release()
            if 0 <= indice < len(itens):
                return itens[indice].value
            if itens:
                return itens[0].value
        except Exception:
            pass
        return ""

    def _janela_id(self, hwnd: int) -> str:
        """Identificador `titulo:classe:exe` que o libobs espera.

        O libobs decodifica assim (libobs/util/windows/window-helpers.c):

            strlist_split(str, ':', true)   -> 3 campos
            strlist[0] = title, [1] = class, [2] = exe
            decode_str(): "#3A" -> ":", depois "#22" -> "#"

        Então todo `:` e todo `#` dentro de título/classe/exe PRECISAM ser
        escapados na ordem inversa ('#' primeiro, senão o "#3A" gerado seria
        corrompido). Sem isso, um título com dois-pontos — "YouTube: vídeo",
        que é o caso normal de navegador — vira 4+ campos, o libobs lê os
        três primeiros e o resto é lixo: janela não encontrada, áudio mudo.
        """
        return self._montar_janela_id(hwnd)

    @staticmethod
    def _escape_janela(t: str) -> str:
        """Escapa como o OBS: '#' -> '#22' e ':' -> '#3A', nessa ordem."""
        return (t or "").replace("#", "#22").replace(":", "#3A")

    def _hwnd_do_pid(self, pid: int) -> int:
        """HWND da maior janela visível de um processo (0 se não achar)."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            melhor = (0, 0)          # (área, hwnd)

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _lp):
                pid_j = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_j))
                if pid_j.value != pid or not user32.IsWindowVisible(hwnd):
                    return True
                r_ = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(r_))
                area = max(0, r_.right) * max(0, r_.bottom)
                nonlocal melhor
                if area > melhor[0]:
                    melhor = (area, int(hwnd or 0))
                return True

            user32.EnumWindows(_cb, 0)
            return melhor[1]
        except Exception:
            return 0

    def _janela_do_pid(self, pid: int) -> str:
        """Acha a janela principal de um processo e devolve o id do libobs.

        Fallback para quando o app só conhece o PID (áudio por processo sem
        hwnd). Usa EnumWindows e escolhe a maior janela visível do processo —
        a janela principal, não um tooltip ou overlay.

        POR QUE IMPORTA: o identificador do libobs é `title:class:exe`. O
        Chrome muda o TÍTULO a cada aba/música — o áudio por processo então
        para de casar e fica mudo no meio da gravação (medido: RMS 0,03 no
        início, 0,002 do meio em diante, sem erro nenhum). Quem grava janela
        de navegador precisa do id ATUALIZADO na hora da troca.
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            candidatas: list[tuple[int, int]] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _lp):
                pid_janela = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_janela))
                if pid_janela.value != pid or not user32.IsWindowVisible(hwnd):
                    return True
                # ignora toolwindows e janelas minúsculas
                estilo = user32.GetWindowLongW(hwnd, -20)   # GWL_EXSTYLE
                if estilo & 0x00000080:                     # WS_EX_TOOLWINDOW
                    return True
                r = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(r))
                area = max(0, r.right) * max(0, r.bottom)
                if area > 10000:
                    candidatas.append((area, int(hwnd or 0)))
                return True

            user32.EnumWindows(_cb, 0)
            if not candidatas:
                return ""
            candidatas.sort(reverse=True)
            return self._montar_janela_id(candidatas[0][1])
        except Exception:
            return ""

    def _montar_janela_id(self, hwnd: int) -> str:
        """Monta o identificador com os escapes que o libobs decodifica."""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        titulo = self._escape_janela(buf.value)

        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        classe = self._escape_janela(cls.value)

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = self._escape_janela(self._executavel_do_pid(pid.value))
        return f"{titulo}:{classe}:{exe}"

    def _executavel_do_pid(self, pid: int) -> str:
        """Nome do .exe de um PID (o window_capture usa no identificador)."""
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED = 0x1000
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, int(pid))
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            tam = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
                return Path(buf.value).name
        finally:
            k32.CloseHandle(h)
        return ""

    def _camera_id(self, nome: str) -> str:
        """Device path da câmera (o dshow_input não aceita nome amigável)."""
        try:
            from pylibobs import Source
            s = Source.create(FONTE_CAMERA, "_probe_cam", {})
            itens = []
            for p in s.get_properties():
                if p.name == "video_device_id":
                    itens = [i for i in p.items if not i.disabled]
                    break
            s.release()
            alvo = (nome or "").strip().lower()
            for i in itens:
                if alvo and alvo in (i.name or "").lower():
                    return i.value
            for i in itens:
                if alvo and alvo in (i.value or "").lower():
                    return i.value
        except Exception:
            pass
        return nome

    # ----------------------------------------------------------- gravação
    def _encoders(self, o: Opcoes):
        """Encoders de vídeo e áudio.

        ATENÇÃO ao `rate_control`: passar ``"rate_control": "CRF"`` faz o
        obs_x264 gerar um arquivo de ~8 KB em 2,5 s (tela preta) em vez de
        1,8 MB. O libobs usa "CRF" ou "CBR" em minúsculas e o campo certo;
        medido nesta máquina, o que funciona é NÃO mandar `rate_control` e
        mandar `crf` (o x264 entra em CRF sozinho), ou mandar
        `rate_control: "CBR"` junto com `bitrate`. Testado:
            {'crf':20}                     -> 1.805.018 bytes
            {'crf':20,'rate_control':'CRF'} ->     8.648 bytes  (quebrado)
        """
        from pylibobs import VideoEncoder, AudioEncoder
        opts_v = {"preset": "veryfast", "bf": 0}
        if o.bitrate_v:
            # CBR de verdade exige os quatro campos juntos
            kbps = int(o.bitrate_v)
            opts_v.update({"rate_control": "CBR", "bitrate": kbps})
        else:
            # CRF: só o `crf`. Sem `rate_control` o x264 escolhe CRF.
            opts_v["crf"] = 20
        venc = VideoEncoder.create("obs_x264", "video", opts_v)
        # O AAC declara a MESMA taxa do contexto. Se divergir, o muxer
        # reamostra de novo e o áudio volta a repetir. A taxa vem da sessão
        # (casada com o dispositivo), não de um 48000 fixo.
        taxa = int(getattr(self, "_taxa_sessao", 0) or 48000)
        aenc = AudioEncoder.create("ffmpeg_aac", "audio",
                                   {"bitrate": int(o.bitrate_a),
                                    "sample_rate": taxa,
                                    "channels": 2})
        return venc, aenc

    def iniciar(self, o: Opcoes) -> Sessao:
        if not self._disponivel:
            raise RuntimeError(f"motor indisponível: {self._motivo}")
        from pylibobs import Output

        sessao = Sessao(opcoes=o, inicio=time.monotonic())
        self._sessao_ativa = sessao

        # ── resolução do canvas ──
        # a posição da câmera sobreposta é calculada em pixels do canvas, então
        # ele tem que estar atualizado ANTES de criar as fontes
        w, h = o.resolucao or self._resolucao_nativa(o)
        self._canvas = (int(w), int(h))
        # a taxa tem que casar com o dispositivo, senão o libobs reamostra e
        # o áudio deriva (ver `_taxa_audio_nativa`). Guarda na sessão para o
        # encoder declarar a mesma.
        self._opcoes_ativas = o
        # a cena aplicada (pelo painel) define o áudio inicial da sessão
        self._cena_viva = getattr(self, "_cena_pendente", None)
        if self._cena_viva:
            logger("motor").info("iniciar: cena ativa '%s' define o áudio "
                                 "(audio=%s)",
                                 self._cena_viva.get("nome"),
                                 self._cena_viva.get("audio"))
        taxa_audio = self._taxa_audio_nativa()
        sessao.taxa_audio = taxa_audio
        self._taxa_sessao = taxa_audio
        try:
            self._ctx.set_video(width=int(w), height=int(h),
                                fps_num=int(o.fps or 30))
            self._ctx.set_audio(samples_per_sec=taxa_audio)
        except Exception as e:
            print(f"[motor] resolução {w}x{h}: {e}")

        # ── cena conforme o modo ──
        fontes = self._fontes_do_modo(o)
        if not fontes:
            raise RuntimeError("nenhuma fonte para o modo escolhido")
        # AVISO DE JANELA QUE VAI SAIR PRETA: minimizada, cloaked pelo DWM ou
        # oculta. O libobs nao reclama — o arquivo so' fica preto — entao o
        # aviso tem que sair daqui, antes de gravar.
        if o.modo == "janela" and o.janela_hwnd:
            motivo = self.motivo_preto(o.janela_hwnd)
            if motivo:
                sessao.aviso = motivo
        cena = self.criar_cena(f"sessao-{int(time.time())}", fontes)
        sessao.cena = cena
        sessao.fontes = fontes
        # item de vídeo da cena: é o que a troca de cena substitui. É a fonte
        # principal (índice 0 — monitor/janela/câmera). As de áudio ficam fora.
        try:
            itens = list(cena.items())
            if itens:
                sessao.itens_video.append(itens[0])
        except Exception:
            pass
        # a sessão passa a ser dona das referências
        sessao.objetos = list(self._refs)
        self._refs.clear()
        # A cena TEM que estar no programa ANTES do output abrir, senão a
        # saída não tem o que renderizar e grava preto (0 bytes durante toda
        # a gravação; 12 KB no fim).
        self.definir_cena(cena)

        # ── saída ──
        ext = (o.formato or "mp4").lower()
        Path(o.saida).parent.mkdir(parents=True, exist_ok=True)
        venc, aenc = self._encoders(o)

        # ── container de gravação ──
        # O `ffmpeg_muxer` do libobs só entende container de VÍDEO bem
        # (mp4/mkv/mov/flv) e, para áudio puro, tem que ser mkv — pedir "mp3"
        # direto gera arquivo de 0 bytes (medido). Então grava o que ele sabe
        # e o `remux.consertar()` converte para mp3/wav/flac no stop.
        formato_mux = ext if ext in FORMATOS_VIDEO else "mkv"
        caminho_gravacao = o.saida
        if ext not in FORMATOS_VIDEO:
            # grava num .mkv temporário ao lado e converte no fim
            caminho_gravacao = str(Path(o.saida).with_suffix(".gravando.mkv"))
        self._caminho_gravacao = caminho_gravacao

        out = Output.create("ffmpeg_muxer", "gravacao",
                            {"path": caminho_gravacao,
                             "format": formato_mux})
        out.set_video_encoder(venc)
        out.set_audio_encoder(aenc)
        sessao.saida = out

        # ── ORDEM MEDIDA ──
        # cena criada -> output criado -> cena no programa -> start.
        # Definir a cena antes de o output existir deixava a saída sem nada
        # para renderizar: 0 bytes durante toda a gravação e 12 KB no fim.
        # Com esta ordem: 2,1 MB em 3 s (prova no mesmo processo).
        self.definir_cena(cena)
        try:
            out.start()
        except Exception as e:
            raise RuntimeError(f"saída não iniciou: {e}")
        return sessao

    def trocar_cena(self, sessao: "Sessao", desc: dict) -> None:
        """Troca a fonte em gravação, sem parar o arquivo.

        Cria a fonte nova, adiciona à cena do programa e remove a anterior.
        O libobs re-renderiza a cena ao vivo; o muxer continua com o mesmo
        arquivo. Testado nesta sessão: 207 -> 121 YAVG com gravação contínua.

        `desc` é o mesmo dicionário de `_fontes_do_modo`:
            {"kind": ..., "nome": ..., "monitor": N}        -> monitor
            {"kind": ..., "nome": ..., "hwnd": N}           -> janela
            {"kind": ..., "nome": ..., "camera": "nome"}    -> câmera
        """
        from pylibobs import Scene as _Scene
        cena = sessao.cena
        _log = logger("motor")
        _log.info("trocar_cena: kind=%s nome=%s (sessão com %d itens de vídeo)",
                  desc.get("kind"), desc.get("nome"), len(sessao.itens_video))
        if cena is None:
            _log.error("trocar_cena: sessão sem cena")
            raise RuntimeError("sessão sem cena")
        # ÁUDIO ONLY: a cena só muda o áudio — pula toda a parte de vídeo
        if desc.get("kind") == "audio_only":
            _log.info("trocar_cena: só áudio (sem troca de vídeo)")
        else:
            # cria a fonte nova e guarda a referência na sessão (o GC do
            # pylibobs libera a fonte e a captura morre — ver Sessao.objetos)
            novo_item, nova_fonte = self._criar_fonte(desc)
            with self._lock_cena:
                # remove o item de vídeo anterior (mantém as fontes de áudio!)
                # o caminho certo é SceneItem.remove() — remove o item DA CENA
                for item_antigo in list(sessao.itens_video):
                    try:
                        item_antigo.remove()
                    except Exception:
                        pass
                    sessao.itens_video.remove(item_antigo)
                # Scene.add espera a SOURCE (obs_source_t); devolve o item
                novo_item = cena.add(nova_fonte)
                sessao.itens_video.append(novo_item)
                sessao.objetos.append(nova_fonte)
                sessao.objetos.append(novo_item)
            _log.info("trocar_cena: vídeo aplicado ao vivo")

        # ── ÁUDIO AO VIVO ──
        # A cena manda no áudio (mic/system/both/none). As fontes já existem
        # na sessão, então aplico mute/unmute — instantâneo, sem glitch.
        audio = (desc.get("audio") or "").lower()
        if audio in ("mic", "system", "both", "none"):
            alvo_mic = audio in ("mic", "both")
            alvo_sys = audio in ("system", "both")
            for fonte in list(sessao.fontes_vivas):
                try:
                    # name é ATRIBUTO no pylibobs (fonte.name), não método —
                    # o erro 'str' object is not callable quebrou TODA a
                    # troca de áudio ao vivo (o log mostrava o ERROR)
                    nome = fonte.name if callable(fonte.name) is False \
                        else fonte.name()
                except Exception:
                    nome = ""
                try:
                    if "Microfone" in str(nome):
                        fonte.muted = not alvo_mic
                        _log.info("áudio ao vivo: %s %s", nome,
                                  "audível" if alvo_mic else "mutado")
                    elif "Áudio" in str(nome):
                        fonte.muted = not alvo_sys
                        _log.info("áudio ao vivo: %s %s", nome,
                                  "audível" if alvo_sys else "mutado")
                except Exception as e:
                    _log.error("mute em %s falhou: %s", nome, e)
            _log.info("trocar_cena: áudio aplicado (mic=%s sistema=%s)",
                      alvo_mic, alvo_sys)

    def _criar_fonte(self, desc: dict):
        """Cria a fonte via o mesmo caminho de _adicionar_fonte, sem cena.

        A fonte é criada e devolvida SEM cena: o item de cena novo é criado
        pelo `trocar_cena` na cena do programa. Guardo a referência da fonte
        antes de qualquer coisa (o GC do pylibobs a libera e a captura morre).
        """
        from pylibobs import Source
        kind = desc.get("kind") or desc.get("tipo")
        nome = desc.get("nome") or kind
        # reaproveita a montagem de settings que _adicionar_fonte faz:
        # cria numa cena descartável e retorna item+fonte
        from pylibobs import Scene as _Scene
        cena_temp = _Scene.create(f"_temp-{int(time.time() * 1000)}")
        try:
            item = self._adicionar_fonte(cena_temp, desc)
        except Exception:
            item = None
        fonte = None
        # _adicionar_fonte anexa [fonte, item] nas refs (nesta ordem). O
        # ÚLTIMO é o item; a FONTE é o penúltimo. Era aqui que o TypeError
        # nascia: eu devolvia o item como fonte e o cena.add(fonte) recebia
        # um obs_sceneitem_t* onde esperava obs_source_t*.
        n = len(self._refs)
        if n >= 2:
            fonte = self._refs[-2]
            item = self._refs[-1]
        elif n == 1:
            fonte = self._refs[-1]
        # destrói a cena temporária — os objetos ficam nas refs da sessão
        try:
            ptr = getattr(cena_temp, "_ptr", None)
            if ptr is not None:
                from pylibobs import _ffi
                _ffi.get_lib().obs_scene_release(ptr)
        except Exception:
            pass
        return item, fonte

    def _fontes_do_modo(self, o: Opcoes) -> list[dict]:
        """Traduz o modo em lista de fontes do libobs."""
        fontes: list[dict] = []

        if o.modo == "monitor":
            fontes.append({"kind": FONTE_MONITOR, "nome": "Monitor",
                           "monitor": o.monitor})
        elif o.modo == "janela":
            if not o.janela_hwnd:
                raise ValueError("janela não selecionada")
            fontes.append({"kind": FONTE_JANELA, "nome": "Janela",
                           "hwnd": o.janela_hwnd})
        elif o.modo == "camera":
            fontes.append({"kind": FONTE_CAMERA, "nome": "Webcam",
                           "camera": o.camera})

        # câmera sobreposta no modo normal — composição de verdade
        if o.camera_sobreposta and o.modo != "camera":
            fontes.append({"kind": FONTE_CAMERA, "nome": "Webcam sobreposta",
                           "camera": o.camera_sobreposta_nome or o.camera,
                           "sobreposta": True,
                           "canto": o.camera_canto,
                           "tamanho": o.camera_tamanho,
                           "borda": o.camera_borda})

        # ── áudio ──
        # ganho_db<=0 = seguir o volume do sistema (volume 1.0, o mixer do
        # Windows manda). Valor >0 multiplica a fonte — é OPCIONAL.
        #
        # TROCA DE CENA AO VIVO: mutar/desmutar é instantâneo, mas criar/
        # remover fonte de áudio num output rodando dá glitch. Então quando
        # há cena aplicada (atributo _cena_aplicada do motor), criamos MIC E
        # SISTEMA SEMPRE e mutamos o que a cena não quer. Sem cena, cria só
        # o que o modo pede (comportamento antigo).
        cena_ativa = getattr(self, "_cena_viva", None)
        if cena_ativa:
            quer_mic = cena_ativa.get("audio") in ("mic", "both")
            quer_sys = cena_ativa.get("audio") in ("system", "both")
            fontes.append({"kind": FONTE_AUDIO_MIC, "nome": "Microfone",
                           "settings": {},
                           "ganho_db": float(o.ganho_mic_db or 0),
                           "mutado": not quer_mic})
            if o.modo == "janela" and o.pid_alvo:
                hwnd_atual = self._hwnd_do_pid(int(o.pid_alvo))
                fontes.append({"kind": FONTE_AUDIO_PROCESSO,
                               "nome": "Áudio app",
                               "pid": o.pid_alvo,
                               "hwnd": hwnd_atual or o.janela_hwnd,
                               "mutado": not quer_sys})
            else:
                fontes.append({"kind": FONTE_AUDIO_SISTEMA,
                               "nome": "Áudio sistema",
                               "settings": {},
                               "ganho_db": float(o.ganho_sys_db or 0),
                               "mutado": not quer_sys})
            logger("motor").info(
                "cena ativa: criando as DUAS fontes de áudio "
                "(mic audível=%s sistema audível=%s)", quer_mic, quer_sys)
            return fontes

        if o.audio in ("mic", "both"):
            fontes.append({"kind": FONTE_AUDIO_MIC, "nome": "Microfone",
                           "settings": {},
                           "ganho_db": float(o.ganho_mic_db or 0)})
        if o.audio in ("system", "both"):
            if o.modo == "janela" and o.pid_alvo:
                # janela = só o áudio dela.
                # re-resolve a janela ATUAL do processo: o título pode ter mudado
                # desde a escolha (YouTube troca o título a cada música), e o id
                # do libobs é title:class:exe — título velho = áudio mudo.
                hwnd_atual = self._hwnd_do_pid(int(o.pid_alvo))
                fontes.append({"kind": FONTE_AUDIO_PROCESSO, "nome": "Áudio app",
                               "pid": o.pid_alvo,
                               "hwnd": hwnd_atual or o.janela_hwnd})
            else:
                fontes.append({"kind": FONTE_AUDIO_SISTEMA, "nome": "Áudio sistema",
                               "settings": {},
                               "ganho_db": float(o.ganho_sys_db or 0)})
        if o.audio == "app" and o.pid_alvo:
            fontes.append({"kind": FONTE_AUDIO_PROCESSO, "nome": "Áudio app",
                           "pid": o.pid_alvo})
        return fontes

    # ----------------------------------------------------------- RTMP
    def iniciar_rtmp(self, sessao: Sessao, url: str, chave: str = "") -> None:
        """Entra ao vivo num destino RTMP, sem parar a gravação."""
        from pylibobs import Output, Service
        servidor, _, chave_url = url.rpartition("/")
        chave_final = chave or chave_url
        svc = Service.create("rtmp_custom", f"svc-{len(sessao.rtmp_urls)}", {
            "server": servidor or url,
            "key": chave_final,
        })
        venc, aenc = self._encoders(sessao.opcoes)
        nome = f"rtmp-{len(sessao.rtmp_urls)}"
        out = Output.create("rtmp_output", nome, {})
        out.set_video_encoder(venc)
        out.set_audio_encoder(aenc)
        out.set_service(svc)
        out.start()
        sessao.rtmp_urls.append(url)

    def parar_rtmp(self, sessao: Sessao, url: str) -> None:
        """Encerra um destino — o libobs identifica por nome, então para todos
        os que casarem com a URL registrada."""
        try:
            from pylibobs import Output
            nome = f"rtmp-{sessao.rtmp_urls.index(url)}"
            out = Output.get_by_name(nome) if hasattr(Output, "get_by_name") else None
            if out is not None:
                out.stop()
            sessao.rtmp_urls = [u for u in sessao.rtmp_urls if u != url]
        except Exception:
            pass

    # apelidos usados pela UI (painel_transmissao)
    adicionar_rtmp = iniciar_rtmp
    remover_rtmp = parar_rtmp

    # ----------------------------------------------------------- controle
    def pausar(self, sessao: Sessao) -> None:
        """Pausa o output de verdade.

        `Output.pause()` do pylibobs tem assinatura `pause(paused: bool = True)`
        — chamar sem argumento PAUSA. Era isso que fazia o "retomar" continuar
        pausado. Aqui o estado é explícito nos dois sentidos.

        Só marco `sessao.pausado` se o libobs confirmar (`out.paused`); antes o
        flag ia para True mesmo quando a chamada não pegava, e a UI dizia
        "pausado" com a gravação correndo.
        """
        _log = logger("motor")
        try:
            sessao.saida.pause(True)
        except Exception as e:
            _log.error("pausar falhou: %s: %s", type(e).__name__, e)
            raise
        confirmado = bool(getattr(sessao.saida, "paused", True))
        sessao.pausado = confirmado
        if confirmado:
            sessao.pausa_desde = time.monotonic()
            _log.info("pausar: output pausado (frame %d)",
                      self.obter_frames(sessao))
        else:
            _log.error("pausar: libobs NÃO confirmou a pausa (out.paused=False)")

    def retomar(self, sessao: Sessao) -> None:
        """Despausa o output. `pause(False)` — NÃO `pause()`, que pausa."""
        _log = logger("motor")
        try:
            # o output do libobs não tem "resume": pausa é toggle booleano
            sessao.saida.pause(False)
        except Exception as e:
            _log.error("retomar falhou: %s: %s", type(e).__name__, e)
            raise
        if bool(getattr(sessao.saida, "paused", False)):
            _log.error("retomar: libobs continuou pausado depois de pause(False)")
            sessao.pausado = True
            return
        # fecha a conta da pausa que acabou
        if sessao.pausa_desde:
            sessao.tempo_pausado += time.monotonic() - sessao.pausa_desde
            sessao.pausa_desde = 0.0
        sessao.pausado = False
        _log.info("retomar: output ativo de novo (tempo pausado acumulado %.1fs)",
                  sessao.tempo_pausado)

    def mudo(self, sessao: Sessao, alvo: str, mudo: bool) -> None:
        """Silencia uma fonte de áudio sem tocar no vídeo."""
        alvo_nome = "Microfone" if alvo == "mic" else "Áudio sistema"
        for fonte in sessao.cena.items() if sessao.cena is not None else []:
            try:
                src = fonte.source if hasattr(fonte, "source") else fonte
                if getattr(src, "name", "") == alvo_nome:
                    src.set_mute(mudo) if hasattr(src, "set_mute") else None
                    return
            except Exception:
                continue

    def obter_frames(self, sessao: Sessao) -> int:
        """Quadros que saíram de fato, direto do libobs.

        Antes eu lia `saida.get_settings()['frames']` — chave que não existe no
        output (o dicionário traz os settings de CONFIGURAÇÃO, não contadores),
        então o painel sempre anunciava "0 quadros" mesmo com o arquivo bom.
        A API certa é `obs_output_get_total_frames(output)`.
        """
        try:
            from pylibobs import _ffi
            lib = _ffi.get_lib()
            ptr = getattr(sessao.saida, "_ptr", None)
            if ptr is None:
                return 0
            return int(lib.obs_output_get_total_frames(ptr) or 0)
        except Exception:
            return 0

    def obter_perdidos(self, sessao: Sessao) -> int:
        """Quadros descartados — antes eu devolvia 0 fixo."""
        try:
            from pylibobs import _ffi
            lib = _ffi.get_lib()
            ptr = getattr(sessao.saida, "_ptr", None)
            if ptr is None:
                return 0
            return int(lib.obs_output_get_frames_dropped(ptr) or 0)
        except Exception:
            return 0

    def _esperar_arquivo_estavel(self, caminho: str,
                                 timeout: float = 20.0) -> int:
        """Espera o muxer terminar de escrever.

        Medido: com 4 s de gravação o arquivo ficava em 15 KB se o `release()`
        viesse logo depois do `stop()`. O libobs fecha o arquivo de forma
        assíncrona; liberar a saída antes trunca. Aqui espera o TAMANHO parar
        de mudar por 3 leituras seguidas.
        """
        p = Path(caminho)
        limite = time.time() + timeout
        ultimo = -1
        estavel = 0
        while time.time() < limite:
            try:
                tam = p.stat().st_size if p.exists() else 0
            except Exception:
                tam = 0
            if tam > 1024 and tam == ultimo:
                estavel += 1
                if estavel >= 3:
                    return tam
            else:
                estavel = 0
            ultimo = tam
            time.sleep(0.15)
        return ultimo if ultimo > 0 else 0

    def parar(self, sessao: Sessao) -> dict:
        resultado = {"frames": 0, "erro": sessao.erro,
                     "rtmp": list(sessao.rtmp_urls)}
        # 1. para o output
        try:
            sessao.saida.stop()
        except Exception as e:
            resultado["erro"] = resultado["erro"] or f"{type(e).__name__}: {e}"

        # 2. espera o arquivo estabilizar ANTES de liberar qualquer coisa
        gravado = getattr(self, "_caminho_gravacao", sessao.opcoes.saida)
        tam = self._esperar_arquivo_estavel(gravado)
        resultado["bytes"] = tam

        # os contadores precisam ser lidos ANTES do release: depois dele o
        # ponteiro do output está morto e a leitura devolve 0
        try:
            resultado["frames"] = self.obter_frames(sessao)
            resultado["perdidos"] = self.obter_perdidos(sessao)
        except Exception:
            pass

        # ── 3. libera as fontes, a cena e a saída ──
        # BUG que isto corrige: as fontes da sessão nunca eram liberadas (eu
        # só soltava cena e saída). O ponteiro Python morria, mas o objeto
        # libobs continuava VIVO segurando o dispositivo WASAPI — a próxima
        # gravação via "Device invalidated. Retrying" no log e o áudio
        # reabria no meio. Cada gravação deixava um conjunto de fontes
        # pendurado, capturando o mesmo dispositivo em paralelo.
        for obj in list(sessao.objetos):
            try:
                if hasattr(obj, "release"):
                    obj.release()
            except Exception:
                pass
        sessao.objetos.clear()
        # o que tiver sobrado em _refs pertence a esta sessão também
        for obj in list(self._refs):
            try:
                if hasattr(obj, "release"):
                    obj.release()
            except Exception:
                pass
        self._refs.clear()
        self._sessao_ativa = None
        self._cena_programa = None
        for obj in (sessao.cena, sessao.saida):
            try:
                obj.release()
            except Exception:
                pass
        # pausa curta: o WASAPI devolve o dispositivo de forma assíncrona
        time.sleep(0.25)

        # 4. conserta container/codec se preciso — DEPOIS do arquivo fechado.
        # Para áudio puro, o arquivo gravado é um .mkv temporário: renomeia
        # para a extensão pedida e deixa o remux converter de verdade.
        try:
            from engine import remux
            final = sessao.opcoes.saida
            if gravado != final and Path(gravado).exists():
                Path(final).unlink(missing_ok=True)
                Path(gravado).rename(final)
            resultado["container"] = remux.consertar(final)
        except Exception as e:
            resultado["container"] = {"consertado": False, "motivo": str(e)}
        try:
            p = Path(sessao.opcoes.saida)
            if p.exists():
                resultado["bytes"] = p.stat().st_size
        except Exception:
            pass

        # campos que o painel de gravação exibe (frames, perdidos, encoder)
        resultado["caminho"] = sessao.opcoes.saida
        resultado["stats"] = {
            "perdidos": resultado.get("perdidos", 0),
            "encoder": "obs_x264",
            "bytes": resultado.get("bytes", 0),
        }
        return resultado

    # ----------------------------------------------------------- fim de vida
    def fechar(self) -> None:
        """Encerra o libobs. A UI chama no fechamento da janela."""
        self.encerrar()
