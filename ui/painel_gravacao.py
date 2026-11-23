"""Aba Gravação — lógica de MODOS do RecorderTab original.

O original não tem um dropdown com 4 fontes: tem dois checkboxes EXCLUSIVOS
("Somente áudio" / "Somente câmera") que trocam o conjunto de controles
visíveis. Copiar isso resolve as incoerências relatadas:

    modo normal      tela/janela + áudio do sistema + microfone + câmera
                     sobreposta + formato de vídeo
    somente câmera   SÓ o seletor de câmera + estilo de borda + formato
                     NADA de áudio do sistema, nada de tela/janela
    somente áudio    SÓ microfone + áudio do sistema + formatos de ÁUDIO
                     (mp3/wav/flac/m4a) — nada de câmera, nada de vídeo

Acessibilidade: mostrar/esconder usa `Show()`+`Layout()`, e o foco é movido
para o primeiro controle visível quando um modo muda.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import wx

from engine.logs import logger
_log = logger("ui.gravacao")

from ui import accessible as a11y
from ui import tones
from ui.i18n import t

# formatos por modo — o original tem exatamente esta separação
FORMATOS_VIDEO = ["mp4", "mkv", "webm", "mov"]
FORMATOS_AUDIO = ["m4a", "mp3", "wav", "flac"]
ESTILOS_BORDA = ["recorder.gradient", "recorder.neonGlow", "recorder.solid"]
CANTOS_CAMERA = ["recorder.topLeft", "recorder.topRight",
                 "recorder.bottomLeft", "recorder.bottomRight"]
TAMANHOS_CAMERA = ["recorder.sizeSmall", "recorder.sizeMedium",
                   "recorder.sizeLarge"]


class PainelGravacao(wx.Panel):
    def __init__(self, pai: wx.Window, speech, motor, cfg: dict) -> None:
        super().__init__(pai)
        self.speech = speech
        self.motor = motor
        self.cfg = cfg

        self.gravando = False
        self.pausado = False
        self.mudo = False
        self._t0 = 0.0
        self._saida = ""
        self._sessao = None

        self.modo_audio = False       # "Somente áudio"
        self.modo_camera = False      # "Somente câmera"

        s = wx.BoxSizer(wx.VERTICAL)

        # ══════════════════════════════════════════ modos exclusivos
        caixa_m = wx.StaticBox(self, -1, "Modo de gravação")
        box_m = wx.StaticBoxSizer(caixa_m, wx.VERTICAL)
        linha_m = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_modo_audio = a11y.caixa(
            caixa_m, lambda: t("recorder.audioOnlyMode"))
        self.chk_modo_audio.Bind(wx.EVT_CHECKBOX, lambda e: self._ao_modo("audio"))
        linha_m.Add(self.chk_modo_audio, 1, wx.RIGHT, 12)
        self.chk_modo_camera = a11y.caixa(
            caixa_m, lambda: t("recorder.cameraOnlyMode"))
        self.chk_modo_camera.Bind(wx.EVT_CHECKBOX, lambda e: self._ao_modo("camera"))
        linha_m.Add(self.chk_modo_camera, 1)
        box_m.Add(linha_m, 0, wx.EXPAND | wx.ALL, 8)
        self.texto_desc_modo = a11y.rotulo(caixa_m, lambda: self._desc_modo())
        box_m.Add(self.texto_desc_modo, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        s.Add(box_m, 0, wx.EXPAND | wx.ALL, 8)

        # ══════════════════════════════════════════ FONTE (tela/janela)
        # escondido em "somente câmera" e "somente áudio"
        self.caixa_fonte = wx.StaticBox(self, -1, t("recorder.screenToRecord"))
        self.box_fonte = wx.StaticBoxSizer(self.caixa_fonte, wx.VERTICAL)
        linha_f = wx.BoxSizer(wx.HORIZONTAL)
        self.escolha_fonte = wx.Choice(
            self.caixa_fonte,
            choices=[t("recorder.fullScreen"), t("recorder.specificWindow")])
        self.escolha_fonte.SetSelection(0)
        self.escolha_fonte.Bind(wx.EVT_CHOICE, lambda e: self._ao_trocar_fonte())
        a11y.aplicar(self.escolha_fonte, a11y.EscolhaAcessivel(
            self.escolha_fonte, t("recorder.screenToRecord")))
        linha_f.Add(self.escolha_fonte, 0, wx.RIGHT, 8)
        self.escolha_alvo = wx.Choice(self.caixa_fonte, choices=["—"])
        a11y.aplicar(self.escolha_alvo, a11y.EscolhaAcessivel(
            self.escolha_alvo, t("recorder.alvoGravacao")))
        linha_f.Add(self.escolha_alvo, 1, wx.RIGHT, 8)
        self.btn_recarregar = a11y.botao(
            self.caixa_fonte, lambda: t("recorder.atualizar"),
            lambda e: self.CarregarAlvos(),
            lambda: t("recorder.atualizarLista"))
        linha_f.Add(self.btn_recarregar, 0)
        self.box_fonte.Add(linha_f, 0, wx.EXPAND | wx.ALL, 8)
        s.Add(self.box_fonte, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ══════════════════════════════════════════ ÁUDIO
        # no modo câmera: escondido (câmera só grava o microfone, se marcado)
        # no modo áudio: só microfone + sistema
        self.caixa_audio = wx.StaticBox(self, -1, "Áudio")
        self.box_audio = wx.StaticBoxSizer(self.caixa_audio, wx.VERTICAL)

        linha_sys = wx.BoxSizer(wx.HORIZONTAL)
        # Checkbox do áudio do sistema. Marcado = captura; desmarcado = não.
        # Desmarcando os DOIS (mic e sistema) o usuário grava sem áudio.
        self.chk_sistema = a11y.caixa(
            self.caixa_audio, lambda: t("recorder.recordSystemAudio"), valor=True)
        self.chk_sistema.Bind(wx.EVT_CHECKBOX, lambda e: self._ao_audio_mudou())
        linha_sys.Add(self.chk_sistema, 1)
        self.box_audio.Add(linha_sys, 0, wx.EXPAND | wx.ALL, 6)

        linha_mic = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_mic = a11y.caixa(
            self.caixa_audio, lambda: t("recorder.microphone"), valor=True)
        self.chk_mic.Bind(wx.EVT_CHECKBOX, lambda e: self._ao_audio_mudou())
        linha_mic.Add(self.chk_mic, 0, wx.RIGHT, 8)
        self.escolha_mic = wx.Choice(
            self.caixa_audio, choices=[t("recorder.selectMicrophone")])
        a11y.aplicar(self.escolha_mic, a11y.EscolhaAcessivel(
            self.escolha_mic, "Dispositivo de microfone"))
        linha_mic.Add(self.escolha_mic, 1)
        self.box_audio.Add(linha_mic, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.texto_aviso_audio = a11y.rotulo(self.caixa_audio,
                                             lambda: self._aviso_audio())
        self.box_audio.Add(self.texto_aviso_audio, 0, wx.ALL, 6)
        s.Add(self.box_audio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ══════════════════════════════════════════ CÂMERA
        # no modo câmera: é a fonte PRINCIPAL (só o seletor de câmera)
        # no modo normal: câmera sobreposta (checkbox "Usar câmera")
        self.caixa_camera = wx.StaticBox(self, -1, "Câmera")
        self.box_camera = wx.StaticBoxSizer(self.caixa_camera, wx.VERTICAL)

        self.chk_camera = a11y.caixa(
            self.caixa_camera, lambda: t("recorder.useCamera"))
        self.chk_camera.Bind(wx.EVT_CHECKBOX, lambda e: self._ao_toggle_camera())
        self.box_camera.Add(self.chk_camera, 0, wx.ALL, 6)

        linha_cam = wx.BoxSizer(wx.HORIZONTAL)
        linha_cam.Add(a11y.rotulo(self.caixa_camera,
                                  lambda: t("recorder.cameraSource")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_camera = wx.Choice(
            self.caixa_camera, choices=[t("recorder.selectCamera")])
        self.escolha_camera.Enable(False)
        a11y.aplicar(self.escolha_camera, a11y.EscolhaAcessivel(
            self.escolha_camera, t("recorder.cameraSource")))
        linha_cam.Add(self.escolha_camera, 1, wx.RIGHT, 8)
        linha_cam.Add(a11y.rotulo(self.caixa_camera,
                                  lambda: t("recorder.cameraBorderStyle")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_borda = wx.Choice(
            self.caixa_camera, choices=[t(e) for e in ESTILOS_BORDA])
        self.escolha_borda.SetSelection(0)
        self.escolha_borda.Enable(False)
        a11y.aplicar(self.escolha_borda, a11y.EscolhaAcessivel(
            self.escolha_borda, t("recorder.cameraBorderStyle")))
        linha_cam.Add(self.escolha_borda, 0)
        self.box_camera.Add(linha_cam, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # ── posição e tamanho da câmera sobreposta ──
        # O painel prometia composição mas não oferecia onde pôr a webcam:
        # ela sempre ia para o canto superior direito com 28% da largura.
        linha_pos = wx.BoxSizer(wx.HORIZONTAL)
        linha_pos.Add(a11y.rotulo(self.caixa_camera,
                                  lambda: t("recorder.cameraPosition")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_canto = wx.Choice(
            self.caixa_camera, choices=[t(e) for e in CANTOS_CAMERA])
        self.escolha_canto.SetSelection(1)      # sup-dir, como o outro app
        a11y.aplicar(self.escolha_canto, a11y.EscolhaAcessivel(
            self.escolha_canto, t("recorder.cameraPosition")))
        linha_pos.Add(self.escolha_canto, 1, wx.RIGHT, 12)

        linha_pos.Add(a11y.rotulo(self.caixa_camera,
                                  lambda: t("recorder.cameraSize")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_tamanho = wx.Choice(
            self.caixa_camera, choices=[t(e) for e in TAMANHOS_CAMERA])
        self.escolha_tamanho.SetSelection(1)    # 28%
        a11y.aplicar(self.escolha_tamanho, a11y.EscolhaAcessivel(
            self.escolha_tamanho, t("recorder.cameraSize")))
        linha_pos.Add(self.escolha_tamanho, 0)

        self.box_camera.Add(linha_pos, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # os dois só fazem sentido quando "Usar câmera" está marcado
        self._habilitar_posicao(False)
        s.Add(self.box_camera, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ══════════════════════════════════════════ FORMATO
        self.caixa_formato = wx.StaticBox(self, -1, t("recorder.outputFormat"))
        self.box_formato = wx.StaticBoxSizer(self.caixa_formato, wx.VERTICAL)
        linha_fmt = wx.BoxSizer(wx.HORIZONTAL)
        self.escolha_formato = wx.Choice(self.caixa_formato,
                                         choices=FORMATOS_VIDEO)
        self.escolha_formato.SetSelection(0)
        a11y.aplicar(self.escolha_formato, a11y.EscolhaAcessivel(
            self.escolha_formato, t("recorder.outputFormat")))
        linha_fmt.Add(self.escolha_formato, 1, wx.RIGHT, 12)
        self.chk_cenas = a11y.caixa(
            self.caixa_formato, lambda: t("recorder.sceneMode"))
        # DESMARCAR o Modo Cena limpa a cena aplicada NA HORA — sem isso a
        # cena velha continuava valendo nas gravações seguintes (o relato do
        # áudio de janela tocando o sistema inteiro era a cena velha de
        # janela persistindo numa gravação "normal").
        self.chk_cenas.Bind(wx.EVT_CHECKBOX, lambda e: self._modo_cena_mudou())
        linha_fmt.Add(self.chk_cenas, 1)
        self.box_formato.Add(linha_fmt, 0, wx.EXPAND | wx.ALL, 8)
        self.texto_formato = a11y.rotulo(self.caixa_formato,
                                         lambda: self._desc_formato())
        self.box_formato.Add(self.texto_formato, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        s.Add(self.box_formato, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # ══════════════════════════════════════════ status e botões
        self.texto_status = a11y.rotulo(self, lambda: self._status_texto())
        s.Add(self.texto_status, 0, wx.EXPAND | wx.ALL, 8)

        self.texto_dica = wx.StaticText(self, label="")
        s.Add(self.texto_dica, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        linha_b = wx.BoxSizer(wx.HORIZONTAL)
        # nome do botão: "Gravar" / "Parar gravação" — o original diz só REC/Stop
        self.btn_principal = a11y.botao(
            self,
            lambda: t("recorder.stop") if self.gravando else t("recorder.rec"),
            self._ao_clicar_principal,
            lambda: self._nome_botao())
        linha_b.Add(self.btn_principal, 2, wx.RIGHT, 8)

        self.btn_pausar = a11y.botao(
            self,
            lambda: (t("recorder.resume") if self.pausado
                     else t("recorder.pause")),
            lambda e: self._alternar_pausa(),
            lambda: (t("recorder.resume") if self.pausado
                     else t("recorder.pause")))
        self.btn_pausar.Enable(False)
        linha_b.Add(self.btn_pausar, 1, wx.RIGHT, 8)

        self.btn_mudo = a11y.botao(
            self, lambda: t("recorder.mudo"), lambda e: self._alternar_mudo(),
            lambda: (t("recorder.reativarMic") if self.mudo
                     else t("recorder.silenciarMic")))
        self.btn_mudo.Enable(False)
        linha_b.Add(self.btn_mudo, 1, wx.RIGHT, 8)

        self.btn_pasta = a11y.botao(
            self, lambda: t("recorder.openFolder"),
            lambda e: self._abrir_pasta(),
            lambda: t("recorder.openFolder"))
        linha_b.Add(self.btn_pasta, 0)
        s.Add(linha_b, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(s)

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._ao_tick, self._timer)

        self.CarregarAlvos()
        self.CarregarDispositivos()
        self._aplicar_modo()

    # ══════════════════════════════════════════════════════ modos
    def _desc_modo(self) -> str:
        if self.modo_camera:
            return t("recorder.cameraOnlyDesc")
        if self.modo_audio:
            return t("recorder.audioOnlyFormatHint")
        return ""

    def _ao_modo(self, qual: str) -> None:
        """Checkboxes exclusivos: marcar um desmarca o outro."""
        if self.gravando:
            return
        if qual == "audio":
            self.modo_audio = self.chk_modo_audio.GetValue()
            if self.modo_audio:
                self.modo_camera = False
                self.chk_modo_camera.SetValue(False)
        else:
            self.modo_camera = self.chk_modo_camera.GetValue()
            if self.modo_camera:
                self.modo_audio = False
                self.chk_modo_audio.SetValue(False)
        self._aplicar_modo()
        self.speech.falar(f"Modo: {self._nome_modo()}")

    def _nome_modo(self) -> str:
        if self.modo_camera:
            return t("recorder.cameraOnlyMode")
        if self.modo_audio:
            return t("recorder.audioOnlyMode")
        return t("recorder.modoNormal")

    def _aplicar_modo(self) -> None:
        """Mostra/esconde seções conforme o modo — igual ao original."""
        audio = self.modo_audio
        camera = self.modo_camera

        # tela/janela: só no modo normal
        self.caixa_fonte.Show(not audio and not camera)
        # áudio: normal e somente-áudio (em câmera, só o mic, se marcado)
        self.caixa_audio.Show(not camera)
        # câmera: normal (sobreposta) e somente-câmera
        self.caixa_camera.Show(camera or not audio)
        # no modo câmera, o checkbox "Usar câmera" não faz sentido:
        # a câmera É a fonte — fica sempre ativa e travado
        if camera:
            self.chk_camera.SetValue(True)
            self.chk_camera.Enable(False)
            self.escolha_camera.Enable(True)
            self.escolha_borda.Enable(True)
            self.CarregarCameras()
        else:
            self.chk_camera.Enable(True)
            self._ao_toggle_camera()

        # formato: vídeo no normal/câmera, áudio no somente-áudio
        self._repopular_formatos()
        self.caixa_formato.Show(True)
        self.chk_cenas.Show(not audio and not camera)

        self._ao_audio_mudou()
        self.Layout()
        # foco no primeiro controle visível do modo
        if camera:
            self.escolha_camera.SetFocus()
        elif audio:
            self.escolha_mic.SetFocus()
        else:
            self.escolha_fonte.SetFocus()

    def _repopular_formatos(self) -> None:
        """Formatos mudam com o modo: vídeo ou áudio puro."""
        if self.modo_audio:
            opcoes = FORMATOS_AUDIO
        else:
            opcoes = FORMATOS_VIDEO
        atual = (self.escolha_formato.GetStringSelection()
                 if self.escolha_formato.GetCount() else "")
        self.escolha_formato.Set(opcoes)
        self.escolha_formato.SetSelection(
            opcoes.index(atual) if atual in opcoes else 0)

    def _desc_formato(self) -> str:
        ext = self.escolha_formato.GetStringSelection()
        if ext in FORMATOS_AUDIO:
            return t("recorder.audioOnlyFormatHint")
        return ""

    # ══════════════════════════════════════════════════════ áudio
    def _aviso_audio(self) -> str:
        """Avisa quando nenhuma fonte de áudio está selecionada."""
        if self.modo_camera:
            return ""
        if not self.chk_mic.GetValue() and not self.chk_sistema.GetValue():
            return "Sem áudio: microfone e sistema desmarcados."
        return ""

    def _ao_audio_mudou(self) -> None:
        tem_mic = self.chk_mic.GetValue()
        self.escolha_mic.Enable(tem_mic)
        self.texto_aviso_audio.SetLabel(self._aviso_audio())
        self.Layout()

    def _habilitar_posicao(self, on: bool) -> None:
        for nome in ("escolha_canto", "escolha_tamanho"):
            c = getattr(self, nome, None)
            if c is not None:
                c.Enable(on)

    def _ao_toggle_camera(self) -> None:
        on = self.chk_camera.GetValue()
        self.escolha_camera.Enable(on)
        self.escolha_borda.Enable(on)
        self._habilitar_posicao(on)
        if on and self.escolha_camera.GetCount() <= 1:
            self.CarregarCameras()
        self.Layout()

    # ══════════════════════════════════════════════════════ listas
    def _fonte_escolhida(self) -> str:
        return "janela" if self.escolha_fonte.GetSelection() == 1 else "monitor"

    def _janelas_cache(self) -> list[dict]:
        """Lista de janelas usada para popular o alvo, guardada junto com o
        índice escolhido.

        POR QUE ISTO EXISTE (bug da janela preta):
        a lista de janelas do Windows muda o tempo todo — abrir/fechar uma aba
        do Chrome, um diálogo, um tooltip. O índice salvo aponta para OUTRA
        janela quando a lista muda de ordem, e o libobs então captura uma
        janela que não está renderizando: o arquivo sai PRETO.

        Medido: o log do app mostrou `update settings` da window-capture com
        `executable: chrome.exe` e SEM `title:` — o plugin resolveu por
        executável e pegou a primeira janela do Chrome, não a escolhida.

        Aqui a lista é guardada no momento em que o alvo é populado, então o
        índice escolhido pelo usuário sempre se refere a ESTA lista. Na hora de
        gravar, o hwnd sai daqui (não de uma chamada nova).
        """
        return getattr(self, "_alvos_janelas", [])

    def CarregarAlvos(self) -> None:
        if not self.motor or not self.motor.disponivel:
            self.escolha_alvo.Set([t("motor.motorIndisponivel")])
            return
        try:
            if self.escolha_fonte.GetSelection() == 0:
                self._alvos_janelas = []
                itens = [f"{m['largura']}x{m['altura']}"
                         + (f" ({t('recorder.monitorPrincipal')})"
                            if m["principal"] else "")
                         for m in self.motor.monitores()]
            else:
                # GUARDA a lista junto com os itens: o índice do Choice passa a
                # ter um significado estável (ver _janelas_cache).
                self._alvos_janelas = self.motor.janelas()
                itens = [j["titulo"][:70] for j in self._alvos_janelas]
        except Exception as e:
            self._alvos_janelas = []
            itens = [f"{t('recorder.erro')}: {e}"]
        self.escolha_alvo.Set(itens or ["—"])
        if itens:
            self.escolha_alvo.SetSelection(0)
        self.Layout()

    def CarregarDispositivos(self) -> None:
        if not self.motor or not self.motor.disponivel:
            return
        try:
            mics = self.motor.microfones()
            self.escolha_mic.Set([t("recorder.selectMicrophone")] +
                                 [m["nome"] + (f" ({t('recorder.padrao')})"
                                               if m["padrao"] else "")
                                  for m in mics])
            if mics:
                self.escolha_mic.SetSelection(1)
        except Exception:
            pass
        self.CarregarCameras()

    def CarregarCameras(self) -> None:
        if not self.motor or not self.motor.disponivel:
            return
        try:
            cams = self.motor.cameras()
            self.escolha_camera.Set([c["nome"] for c in cams] or
                                    [t("recorder.selectCamera")])
            if cams:
                self.escolha_camera.SetSelection(0)
        except Exception:
            pass

    def _ao_trocar_fonte(self) -> None:
        self.CarregarAlvos()
        self.texto_dica.SetLabel("")
        self.Layout()

    # ══════════════════════════════════════════════════════ estado
    def _status_texto(self) -> str:
        if not self.gravando:
            return t("recorder.statusReady")
        # O cronômetro vem da SESSÃO, que desconta o tempo em pausa
        # (`Sessao.decorrido`). Antes era `monotonic() - _t0` aqui mesmo: com a
        # gravação parada na pausa, os segundos continuavam andando — o usuário
        # relatou exatamente isso ("diz que está gravando e os segundos andam").
        sessao = self._sessao
        d = int(sessao.decorrido()) if sessao is not None else \
            int(time.monotonic() - self._t0)
        mm, ss = divmod(max(0, d), 60)
        pausado = bool(sessao.pausado) if sessao is not None else self.pausado
        base = t("recorder.paused") if pausado else t("recorder.recordingNow")
        mudo = " — microfone mudo" if self.mudo else ""
        extra = f" — {Path(self._saida).name}" if self._saida else ""
        return f"{base} {mm:02d}:{ss:02d}{mudo}{extra}"

    def _nome_botao(self) -> str:
        if self.gravando:
            return t("recorder.stop")
        alvo = (self.escolha_alvo.GetStringSelection()
                if not self.modo_camera and not self.modo_audio
                else self.escolha_camera.GetStringSelection()
                if self.modo_camera else "microfone e sistema")
        return f'{t("recorder.rec")}: {self._nome_modo()} — {alvo}'

    # ══════════════════════════════════════════════════════ gravação
    def _ao_clicar_principal(self, _evt=None) -> None:
        if self.gravando:
            self.parar()
        else:
            self.gravar()

    def _montar_opcoes_da_cena(self, cena: dict):
        """Opções construídas a partir do PRESET da cena ativa.
        (o ganho vem de engine.config.ganho_db, que tolera o texto da opção)

        A cena manda em vídeo e áudio. O que continua vindo da UI:
        formato, pasta, bitrates, ganhos, resolução — configuração do app,
        não da cena.
        """
        from engine.motor_obs import Opcoes
        from engine.config import ganho_db

        fonte = cena.get("fonte", "monitor")
        audio = cena.get("audio", "both")
        modo = {"monitor": "monitor", "janela": "janela", "camera": "camera",
                "none": "audio", "sem vídeo": "audio"}.get(fonte, "monitor")

        pasta = self.cfg.get("folder") or str(Path.home() / "Videos")
        Path(pasta).mkdir(parents=True, exist_ok=True)
        ext = self.escolha_formato.GetStringSelection()
        saida = str(Path(pasta) / time.strftime(
            f"Eternal Recorder %Y-%m-%dT%H-%M-%S.{ext}"))

        o = Opcoes(
            modo=modo, fps=int(self.cfg.get("fps", 30) or 30),
            saida=saida, formato=ext, audio=audio,
            bitrate_v=int(self.cfg.get("videoBitrate", 2500) or 0),
            bitrate_a=int(self.cfg.get("audioBitrate", 192) or 192),
            ganho_mic_db=ganho_db(self.cfg.get("micGain", "")),
            ganho_sys_db=ganho_db(self.cfg.get("sysGain", "")),
        )
        res = self.cfg.get("resolution", "source")
        if res and res != "source" and modo != "audio":
            try:
                w, h = (int(x) for x in str(res).lower().split("x"))
                o.resolucao = (w, h)
            except Exception:
                pass

        # alvo conforme a fonte da cena
        try:
            if modo == "monitor":
                o.monitor = max(0, int(cena.get("indice", 0)))
            elif modo == "janela":
                janelas = self.motor.janelas() if self.motor else []
                i = max(0, int(cena.get("indice", 0)))
                # primeiro pelo índice salvo; se o título divergiu (janelas
                # mudam de ordem), procura PELO TÍTULO salvo na cena
                if i < len(janelas) and                         janelas[i]["titulo"][:70] == str(cena.get("alvo"))[:70]:
                    o.janela_hwnd = janelas[i]["hwnd"]
                    o.pid_alvo = janelas[i]["pid"]
                else:
                    alvo = str(cena.get("alvo", ""))[:70]
                    for j in janelas:
                        if j["titulo"][:70] == alvo:
                            o.janela_hwnd = j["hwnd"]
                            o.pid_alvo = j["pid"]
                            break
                # SEM pid = o áudio cairia no SISTEMA INTEIRO (o else do
                # motor). Se não achou a janela, avisa em vez de engolir.
                if o.pid_alvo == 0 and audio in ("system", "both"):
                    raise RuntimeError(
                        "A janela da cena não está mais aberta. Reabra o "
                        "programa e atualize a cena.")
            elif modo == "camera":
                o.camera = cena.get("alvo", "")
        except Exception:
            pass

        # câmera sobreposta, conforme a cena
        if modo in ("monitor", "janela") and cena.get("cam_sobre"):
            o.camera_sobreposta = True
            cams = self.motor.cameras() if self.motor else []
            o.camera_sobreposta_nome = cams[0]["nome"] if cams else None
            canto = cena.get("canto", "")
            o.camera_canto = {"sup. esquerdo": "sup_esq", "sup. direito": "sup_dir",
                              "inf. esquerdo": "inf_esq",
                              "inf. direito": "inf_dir"}.get(canto, "sup_dir")
            tam = cena.get("tamanho", "média")
            o.camera_tamanho = {"pequena": 0.18, "média": 0.28,
                                "grande": 0.38}.get(tam, 0.28)
        return o

    def _montar_opcoes(self):
        from engine.motor_obs import Opcoes
        from engine.config import ganho_db

        # ── CENA ATIVA MANDA NO PRESET ──
        # Se há cena ativada na aba Cenas, ela define vídeo e áudio da
        # gravação. Isso era o bug: a cena "ativava" (falava) e a gravação
        # ignorava. Medido antes do conserto: cena "somente áudio" gravava
        # com monitor, porque nada era aplicado.
        cena = getattr(self, "cena_aplicada", None)
        # A cena SÓ VALE com o "Modo Cena" MARCADO. Desmarcou = gravação
        # normal, com a fonte/áudio escolhidos na aba (relato: gravava com
        # o áudio de janela mesmo sem cena, ou o sistema inteiro).
        if cena and self.chk_cenas.GetValue():
            return self._montar_opcoes_da_cena(cena)
        # sem modo cena: descarta a cena aplicada e a pendência do motor
        if cena:
            self.cena_aplicada = None
        if self.motor and getattr(self.motor, "_cena_pendente", None):
            self.motor._cena_pendente = None
        if self.motor and getattr(self.motor, "_cena_viva", None):
            self.motor._cena_viva = None

        if self.modo_camera:
            modo = "camera"
        elif self.modo_audio:
            modo = "audio"
        else:
            modo = self._fonte_escolhida()

        pasta = self.cfg.get("folder") or str(Path.home() / "Videos")
        Path(pasta).mkdir(parents=True, exist_ok=True)
        ext = self.escolha_formato.GetStringSelection()
        saida = str(Path(pasta) / time.strftime(
            f"Eternal Recorder %Y-%m-%dT%H-%M-%S.{ext}"))

        # áudio: decide pelo que está MARCADO, não pelo modo
        quer_mic = self.chk_mic.GetValue()
        quer_sys = self.chk_sistema.GetValue()
        if self.modo_camera:
            # câmera só tem microfone como áudio possível
            audio = "mic" if quer_mic else "none"
        elif quer_mic and quer_sys:
            audio = "both"
        elif quer_mic:
            audio = "mic"
        elif quer_sys:
            audio = "system"
        else:
            audio = "none"

        o = Opcoes(
            modo=modo, fps=int(self.cfg.get("fps", 30) or 30),
            saida=saida, formato=ext, audio=audio,
            bitrate_v=int(self.cfg.get("videoBitrate", 2500) or 0),
            bitrate_a=int(self.cfg.get("audioBitrate", 192) or 192),
            ganho_mic_db=ganho_db(self.cfg.get("micGain", "")),
            ganho_sys_db=ganho_db(self.cfg.get("sysGain", "")),
        )
        res = self.cfg.get("resolution", "source")
        if res and res != "source" and modo != "audio":
            try:
                w, h = (int(x) for x in str(res).lower().split("x"))
                o.resolucao = (w, h)
            except Exception:
                pass

        if modo == "monitor":
            o.monitor = max(0, self.escolha_alvo.GetSelection())
        elif modo == "janela":
            # ── HWND DO CACHE, NAO DA LISTA NOVA ──
            # O índice do Choice foi escolhido sobre a lista que CarregarAlvos()
            # mostrou. Chamar motor.janelas() de novo aqui pegava uma lista
            # DIFERENTE (o Chrome abre/fecha janelas o tempo todo) e o índice
            # apontava para outra janela — a captura saía PRETA.
            # Medido: log do app com `executable: chrome.exe` e sem `title:`.
            janelas = self._janelas_cache()
            i = self.escolha_alvo.GetSelection()
            if 0 <= i < len(janelas):
                o.janela_hwnd = janelas[i]["hwnd"]
                o.pid_alvo = janelas[i]["pid"]
            else:
                # cache vazio (lista nunca carregada ou fonte trocada agora):
                # recarrega e usa o índice, mas avisa se não casar.
                janelas = self.motor.janelas() if self.motor else []
                if 0 <= i < len(janelas):
                    o.janela_hwnd = janelas[i]["hwnd"]
                    o.pid_alvo = janelas[i]["pid"]
                elif janelas:
                    o.janela_hwnd = janelas[0]["hwnd"]
                    o.pid_alvo = janelas[0]["pid"]
        elif modo == "camera":
            o.camera = self.escolha_camera.GetStringSelection()

        # ── câmera sobreposta (composição) ──
        # BUG que isto corrige: a caixa "Usar câmera" existia na aba Gravador,
        # mas o valor dela NUNCA ia para as Opções — o motor recebia
        # camera_sobreposta=False sempre e a webcam não aparecia em tela cheia
        # nem em janela. O outro Eternal Recorder mostra a câmera no canto; é
        # isso que estas três linhas ligam.
        if modo in ("monitor", "janela"):
            marcar = bool(self.chk_camera.GetValue())
            o.camera_sobreposta = marcar
            if marcar:
                cam = self.escolha_camera.GetStringSelection()
                if cam and cam != t("recorder.selectCamera"):
                    o.camera_sobreposta_nome = cam
                else:
                    # sem escolha explícita, usa a primeira que existir
                    cams = self.motor.cameras() if self.motor else []
                    o.camera_sobreposta_nome = cams[0]["nome"] if cams else None
                # as próximas opções vêm dos controles de posição/borda
                o.camera_canto = self._canto_escolhido()
                o.camera_tamanho = self._tamanho_camera()
                o.camera_borda = self._borda_escolhida()

        if quer_mic and self.escolha_mic.GetSelection() > 0:
            o.mic_indice = self.escolha_mic.GetSelection() - 1
        return o

    # ── posição/tamanho/borda da câmera sobreposta ──
    def _canto_escolhido(self) -> str:
        """Canto da tela onde a webcam é desenhada."""
        try:
            i = self.escolha_canto.GetSelection() if hasattr(self, "escolha_canto") else 1
        except Exception:
            i = 1
        return {0: "sup-esq", 1: "sup-dir", 2: "inf-esq", 3: "inf-dir"}.get(i, "sup-dir")

    def _tamanho_camera(self) -> float:
        """Fração da largura da tela que a webcam ocupa (0.15–0.45)."""
        try:
            i = self.escolha_tamanho.GetSelection() if hasattr(self, "escolha_tamanho") else 1
        except Exception:
            i = 1
        return {0: 0.18, 1: 0.28, 2: 0.38}.get(i, 0.28)

    def _borda_escolhida(self) -> str:
        """Estilo da borda: solida | gradiente | neon | nenhuma."""
        try:
            i = self.escolha_borda.GetSelection() if hasattr(self, "escolha_borda") else 0
        except Exception:
            i = 0
        return {0: "solida", 1: "gradiente", 2: "neon", 3: "nenhuma"}.get(i, "solida")

    def gravar(self) -> None:
        _log.info("=== gravar() pedindo início (gravando=%s) ===",
                  self.gravando)
        if self.gravando:
            _log.warning("gravar() ignorado: já gravando")
            return
        if not self.motor or not self.motor.disponivel:
            msg = ("Motor de captura indisponível: "
                   + (self.motor.motivo if self.motor else "não carregado"))
            self.texto_dica.SetLabel(msg)
            self.Layout()
            self.speech.falar(msg, interrupt=True)
            tones.erro()
            return
        try:
            opcoes = self._montar_opcoes()
        except Exception as e:
            self.texto_dica.SetLabel(f"Erro: {e}")
            self.Layout()
            self.speech.falar(f"Erro ao preparar: {e}", interrupt=True)
            tones.erro()
            return

        self._saida = opcoes.saida
        _log.info("opções: modo=%s audio=%s formato=%s ganho_mic=%s "
                  "ganho_sys=%s saida=%s", opcoes.modo, opcoes.audio,
                  opcoes.formato, opcoes.ganho_mic_db, opcoes.ganho_sys_db,
                  opcoes.saida)
        self.gravando = True
        self.pausado = False
        self._t0 = time.monotonic()
        self.btn_principal.SetLabel(t("recorder.stop"))
        self.btn_pausar.Enable(True)
        self.btn_mudo.Enable(opcoes.audio in ("mic", "both"))
        self.texto_status.SetLabel(self._status_texto())
        self.texto_dica.SetLabel("Iniciando…")
        self.Layout()
        self._timer.Start(500)
        # ── ORDEM DO SOM (importa: o bipe sai pelo dispositivo que a captura
        # grava). O tom toca JÁ (feedback imediato ao clique) e a thread
        # espera ele terminar ANTES de abrir a captura — senão o próprio
        # "iniciando" entra nos primeiros quadros do arquivo.
        tones.inicio()
        self.speech.falar(t("recorder.statusRecordingStarted"), interrupt=True)

        def _iniciar():
            try:
                tones.aguardar(1.0)
                sessao = self.motor.iniciar(opcoes)
                wx.CallAfter(self._ao_iniciado, sessao)
            except Exception as e:
                wx.CallAfter(self._ao_falhou, f"{type(e).__name__}: {e}")

        threading.Thread(target=_iniciar, daemon=True,
                         name="iniciar-gravacao").start()

    def aplicar_cena(self, cena: dict) -> None:
        """Aplica a cena ativada na aba Cenas.

        GRAVANDO: troca a fonte de vídeo ao vivo (o arquivo continua; medido
        nesta sessão: 207 -> 121 YAVG sem parar o muxer).
        NÃO GRAVANDO: guarda o preset; a próxima gravação usa
        `_montar_opcoes_da_cena`.

        As fontes de áudio NÃO são trocadas ao vivo — o libobs não aceita
        adicionar/remover fontes de áudio num output rodando sem glitch; o
        áudio da cena vale na PRÓXIMA gravação (a fala já avisa isso).
        """
        self.cena_aplicada = cena
        nome = cena.get("nome", "")
        _log.info("aplicar_cena(%s): gravando=%s sessao=%s",
                  nome, self.gravando, self._sessao is not None)
        if self.gravando and self._sessao is not None and self.motor:
            desc = self._desc_da_cena(cena)
            if desc is None:
                self.speech.falar(
                    f"Cena {nome}: sem vídeo para trocar ao vivo. "
                    f"Aplica na próxima gravação.", interrupt=True)
                return
            try:
                self.motor.trocar_cena(self._sessao, desc)
                self.motor._cena_viva = cena      # a viva passa a ser esta
                self.speech.falar(
                    f"Cena {nome} aplicada ao vivo: "
                    f"{desc.get('kind', '')}. Áudio: "
                    f"{cena.get('audio_label', '')}.", interrupt=True)
            except Exception as e:
                self.speech.falar(
                    f"Erro ao trocar cena: {e}", interrupt=True)
        else:
            # sem gravação: guarda no motor — o INICIAR vai criar as duas
            # fontes de áudio e deixar audível só o que a cena pede
            if self.motor:
                self.motor._cena_pendente = cena
            self.speech.falar(
                f"Cena {nome} preparada. {cena.get('audio_label', '')}. "
                f"Vale na próxima gravação.", interrupt=True)

    def _desc_da_cena(self, cena: dict):
        """Traduz a cena para o dict que o motor.trocar_cena espera.

        Inclui o ÁUDIO da cena: o motor aplica mute/unmute nas fontes vivas
        da sessão (instantâneo). Mesmo quando a fonte de vídeo é a MESMA
        (duas cenas de monitor, por exemplo), o áudio muda — era o caso do
        usuário: cenas 1 e 2 ambas monitor, mas mic vs sistema.
        """
        fonte = cena.get("fonte", "")
        audio = cena.get("audio", "")
        if fonte == "monitor":
            return {"kind": "monitor_capture", "nome": "Monitor",
                    "monitor": max(0, int(cena.get("indice", 0))),
                    "audio": audio}
        if fonte == "janela":
            janelas = self.motor.janelas() if self.motor else []
            i = max(0, int(cena.get("indice", 0)))
            if i >= len(janelas):
                return None
            return {"kind": "window_capture", "nome": "Janela",
                    "hwnd": janelas[i]["hwnd"], "audio": audio}
        if fonte == "camera":
            return {"kind": "dshow_input", "nome": "Webcam",
                    "camera": cena.get("alvo", ""), "audio": audio}
        # "sem vídeo" — não troca imagem, MAS o áudio ainda pode mudar
        return {"kind": "audio_only", "nome": "Áudio", "audio": audio}

    def _modo_cena_mudou(self) -> None:
        """Modo Cena desmarcado = nenhuma cena vale mais."""
        if self.chk_cenas.GetValue():
            self.speech.falar("Modo cena ativado. Escolha uma cena na aba "
                              "Cenas.", interrupt=True)
            return
        self.cena_aplicada = None
        if self.motor:
            self.motor._cena_pendente = None
            self.motor._cena_viva = None
        self.speech.falar("Modo cena desativado. A gravação usa a fonte e o "
                          "áudio escolhidos aqui.", interrupt=True)

    def _travar_opcoes(self, travar: bool) -> None:
        """Trava as opções de CONTEÚDO durante a gravação.

        BUG relatado: com a gravação rodando, o usuário desmarcava
        microfone/áudio do sistema e trocava a fonte — nada mudava no arquivo
        (as opções só valem no iniciar) e parecia que o app tinha ignorado.
        Pior: ao trocar o áudio, o usuário ACHAVA que estava gravando sem som.

        O que fica travado: fonte, alvo, checkboxes de áudio, câmera,
        formato. O que NÃO trava: pausar, mudo, parar — ações da sessão.
        """
        for controle in (self.escolha_fonte, self.escolha_alvo,
                         self.escolha_formato, self.chk_mic,
                         self.chk_sistema, self.chk_camera,
                         self.chk_cenas):
            try:
                controle.Enable(not travar)
            except Exception:
                pass

    def _ao_iniciado(self, sessao) -> None:
        self._sessao = sessao
        if sessao.erro:
            self._ao_falhou(sessao.erro)
            return
        self._travar_opcoes(True)
        aviso = getattr(sessao, "aviso", None)
        self.texto_dica.SetLabel(
            aviso or f"Gravando — {sessao.trilhas_audio} trilha(s) de áudio")
        self.Layout()
        if aviso:
            self.speech.falar(aviso)

    def _ao_falhou(self, erro: str) -> None:
        self._timer.Stop()
        self.gravando = False
        self.btn_principal.SetLabel(t("recorder.rec"))
        self.btn_pausar.Enable(False)
        self.btn_mudo.Enable(False)
        self._travar_opcoes(False)
        self.texto_status.SetLabel(t("recorder.statusReady"))
        self.texto_dica.SetLabel(f"Erro: {erro}")
        self.Layout()
        tones.erro()
        self.speech.falar(f"Erro ao gravar. {erro}", interrupt=True)

    def _alternar_pausa(self) -> None:
        """Alterna pausa/retomada olhando o estado REAL do output.

        Antes o flag `self.pausado` era invertido ANTES de chamar o motor e
        nunca era conferido depois: com `retomar()` quebrado (chamava
        `pause()` sem argumento, que pausa), o botão virava "Pausar", o status
        dizia "Gravando" e o arquivo ficava congelado — o relato do usuário.
        Agora: lê o estado, age, e sincroniza o flag com o que o libobs
        confirmou.
        """
        if not self.gravando or self._sessao is None:
            return
        sessao = self._sessao
        pausado_agora = bool(getattr(sessao, "pausado", self.pausado))
        try:
            if pausado_agora:
                self.motor.retomar(sessao)
            else:
                self.motor.pausar(sessao)
        except Exception as e:
            _log.error("alternar_pausa falhou: %s: %s", type(e).__name__, e)
            self.speech.falar(f"Erro ao pausar: {e}", interrupt=True)
            # não deixa a UI mentindo sobre o estado
            self.pausado = bool(getattr(sessao, "pausado", self.pausado))
            self._atualizar_botao_pausa()
            self.texto_status.SetLabel(self._status_texto())
            self.Layout()
            return

        self.pausado = bool(getattr(sessao, "pausado", not pausado_agora))
        if self.pausado:
            # output JÁ pausado: o tom de pausa não entra no arquivo
            tones.pausa()
            self.speech.falar(t("recorder.statusRecordingPaused"),
                              interrupt=True)
        else:
            tones.retomada()
            self.speech.falar(t("recorder.statusRecordingResumed"),
                              interrupt=True)
        self._atualizar_botao_pausa()
        self.texto_status.SetLabel(self._status_texto())
        self.Layout()

    def _atualizar_botao_pausa(self) -> None:
        self.btn_pausar.SetLabel(
            t("recorder.resume") if self.pausado else t("recorder.pause"))

    def _alternar_mudo(self) -> None:
        if not self.gravando or self._sessao is None:
            return
        self.mudo = not self.mudo
        try:
            self.motor.mudo(self._sessao, "mic", self.mudo)
        except Exception as e:
            self.speech.falar(f"Erro ao silenciar: {e}", interrupt=True)
            return
        self.speech.falar(t("recorder.statusMicMuted") if self.mudo
                          else t("recorder.statusMicUnmuted"), interrupt=True)
        self.texto_status.SetLabel(self._status_texto())
        self.Layout()

    def parar(self) -> None:
        _log.info("=== parar() (gravando=%s) ===", self.gravando)
        if not self.gravando:
            _log.warning("parar() ignorado: não estava gravando")
            return
        self._timer.Stop()
        self.gravando = False
        self.pausado = False
        self.btn_principal.SetLabel(t("recorder.rec"))
        self.btn_pausar.Enable(False)
        self.btn_mudo.Enable(False)
        self._travar_opcoes(False)      # opções voltam a poder ser trocadas
        self.texto_status.SetLabel(t("recorder.statusReady"))
        self.Layout()
        # o tom de fim toca depois de a captura fechar (na thread _parar),
        # senão ele entra nos últimos quadros do arquivo
        self.speech.falar(t("recorder.statusRecordingStopped"), interrupt=True)

        sessao, self._sessao = self._sessao, None
        caminho = self._saida

        def _parar():
            if sessao is None:
                return
            try:
                res = self.motor.parar(sessao)
            except Exception as e:
                res = {"erro": f"{type(e).__name__}: {e}"}
            tones.fim()          # captura fechada: agora o bipe não contamina
            wx.CallAfter(self._ao_parado, res, caminho)

        threading.Thread(target=_parar, daemon=True,
                         name="parar-gravacao").start()

    def _ao_parado(self, res: dict, caminho: str) -> None:
        st = res.get("stats") or {}
        if res.get("erro"):
            self.texto_dica.SetLabel(f"Erro: {res['erro']}")
            tones.erro()
            self.speech.falar(f"Erro ao finalizar. {res['erro']}", interrupt=True)
        else:
            self.texto_dica.SetLabel(
                f"Salvo: {caminho} — {res.get('frames', 0)} frames, "
                f"{st.get('perdidos', 0)} perdidos, {st.get('encoder', '?')}")
            # som de "salvo" DEPOIS do tom de fim: são dois eventos diferentes
            # — a gravação parou e o arquivo foi escrito no disco. Quem não vê
            # a tela precisa saber que pode ir embora com o arquivo pronto.
            tones.salvo()
            self.speech.falar(
                f"Gravação salva. {res.get('frames', 0)} quadros.",
                interrupt=True)
        self.Layout()

    def _abrir_pasta(self) -> None:
        pasta = self.cfg.get("folder") or str(Path.home() / "Videos")
        try:
            import subprocess
            import sys as _sys
            flags = 0x08000000 if _sys.platform == "win32" else 0
            subprocess.Popen(["explorer", pasta], creationflags=flags)
            self.speech.falar("Abrindo pasta de gravações")
        except Exception as e:
            self.speech.falar(f"{t('recorder.openFolderFailed')}: {e}",
                              interrupt=True)

    def _ao_tick(self, _evt) -> None:
        # repinta; NÃO fala
        self.texto_status.SetLabel(self._status_texto())
        self.Layout()
