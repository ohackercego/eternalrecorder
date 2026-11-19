"""Aba Transmissão: destinos RTMP ao vivo, com presets de plataforma.

Espelha o TransmissionTab do build Electron. O motor já suporta RTMP
(`add-rtmp`/`remove-rtmp`) sem parar a gravação — é o mesmo caminho que o
sidecar validou com 203 KB / 8,64 s.
"""
from __future__ import annotations

import wx

from ui import accessible as a11y
from ui.i18n import t

PRESETS = {
    "twitch": "rtmp://live.twitch.tv/app/",
    "youtube": "rtmp://a.rtmp.youtube.com/live2/",
    "facebook": "rtmps://live-api-s.facebook.com:443/rtmp/",
}


class PainelTransmissao(wx.Panel):
    def __init__(self, pai: wx.Window, speech, config: dict) -> None:
        super().__init__(pai)
        self.speech = speech
        self.cfg = config
        self._destinos: list[dict] = list(config.get("rtmp", []))
        # estado ANTES dos botoes: o rotulo do botao ao vivo e um callable que
        # consulta self._ativo, e ele e chamado durante a construcao
        self._ativo = False
        self._motor = None
        self._sessao = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(a11y.rotulo(self, lambda: t("transmission.title")), 0,
                  wx.ALL, 10)

        # ── lista de destinos ──
        caixa = wx.StaticBoxSizer(wx.VERTICAL, self, t("transmission.rtmpDestinations"))
        self.lista = a11y.lista(
            self, lambda: t("transmission.rtmpDestinations"), tamanho=(-1, 140))
        self.lista.InsertColumn(0, t("transmission.title"), width=200)
        self.lista.InsertColumn(1, "URL", width=380)
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: self._anunciar_item())
        caixa.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)
        sizer.Add(caixa, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # ── adicionar destino ──
        caixa2 = wx.StaticBoxSizer(wx.VERTICAL, self, t("transmission.add"))
        linha1 = wx.BoxSizer(wx.HORIZONTAL)
        linha1.Add(a11y.rotulo(self, lambda: t("transmission.custom")), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_preset = wx.Choice(self, choices=[
            t("transmission.twitch"), t("transmission.youtube"),
            t("transmission.facebook"), t("transmission.custom")])
        self.escolha_preset.SetSelection(3)
        self.escolha_preset.Bind(wx.EVT_CHOICE, lambda e: self._aplicar_preset())
        a11y.aplicar(self.escolha_preset, a11y.EscolhaAcessivel(
            self.escolha_preset, t("transmission.custom")))
        linha1.Add(self.escolha_preset, 1)
        caixa2.Add(linha1, 0, wx.EXPAND | wx.ALL, 8)

        linha2 = wx.BoxSizer(wx.HORIZONTAL)
        linha2.Add(a11y.rotulo(self, lambda: "URL RTMP"), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.campo_url = wx.TextCtrl(self, value="rtmp://")
        a11y.aplicar(self.campo_url, a11y.CampoAcessivel(self.campo_url,
                                                         "URL RTMP"))
        linha2.Add(self.campo_url, 1)
        caixa2.Add(linha2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        linha3 = wx.BoxSizer(wx.HORIZONTAL)
        linha3.Add(a11y.rotulo(self, lambda: t("transmission.streamKey")), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.campo_chave = wx.TextCtrl(self, value="", style=wx.TE_PASSWORD)
        a11y.aplicar(self.campo_chave, a11y.CampoAcessivel(
            self.campo_chave, t("transmission.streamKey")))
        linha3.Add(self.campo_chave, 1)
        caixa2.Add(linha3, 0, wx.EXPAND | wx.ALL, 8)

        linha4 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_add = a11y.botao(
            self, lambda: t("transmission.addDestination"),
            lambda e: self._adicionar(), lambda: t("transmission.addDestination"))
        linha4.Add(self.btn_add, 1, wx.RIGHT, 8)
        self.btn_remover = a11y.botao(
            self, lambda: t("transmission.remove"),
            lambda e: self._remover(), lambda: t("transmission.remove"))
        linha4.Add(self.btn_remover, 1)
        caixa2.Add(linha4, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(caixa2, 0, wx.EXPAND | wx.ALL, 10)

        # ── O QUE É TRANSMITIDO (preset/cena) ──
        # Era o buraco relatado: a aba de transmissão só tinha URL RTMP e o
        # botão "ao vivo" — nada de tela, microfone, áudio do sistema, cenas
        # ou câmera. O usuário perguntou "cadê a configuração de tela,
        # microfone, áudio do sistema, cenas, somente câmera etc?"
        #
        # Resposta de design: a transmissão COMPARTILHA a fonte da gravação
        # (o libobs manda a mesma cena para os dois outputs), então a escolha
        # de O QUE vai ao ar é o preset da cena — o mesmo seletor da aba
        # Cenas, aqui em modo resumo com atalho para editar. Duplicar os
        # controles faria os dois lugares divergirem.
        caixa3 = wx.StaticBoxSizer(wx.VERTICAL, self, "O que vai ao ar")
        self.texto_fonte = a11y.rotulo(
            self, lambda: self._resumo_fonte())
        caixa3.Add(self.texto_fonte, 0, wx.ALL, 8)
        l_cena = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_abrir_cenas = a11y.botao(
            self, lambda: "Escolher cena / preset",
            lambda e: self._abrir_cenas(),
            lambda: "Abrir a aba Cenas para escolher o que vai ao ar")
        l_cena.Add(self.btn_abrir_cenas, 1, wx.RIGHT, 8)
        self.chk_cam_sobre_tx = a11y.caixa(
            self, lambda: "Incluir câmera sobreposta")
        self.chk_cam_sobre_tx.SetValue(True)
        l_cena.Add(self.chk_cam_sobre_tx, 1)
        caixa3.Add(l_cena, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(caixa3, 0, wx.EXPAND | wx.ALL, 10)

        # ── ao vivo ──
        linha5 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_ao_vivo = a11y.botao(
            self, lambda: (t("transmission.stopStreaming")
                           if self._ativo else t("transmission.startStreaming")),
            lambda e: self._alternar_live(),
            lambda: self._nome_botao_live())
        linha5.Add(self.btn_ao_vivo, 1)
        sizer.Add(linha5, 0, wx.EXPAND | wx.ALL, 10)

        self.texto_status = a11y.rotulo(self, lambda: self._status())
        sizer.Add(self.texto_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.SetSizer(sizer)
        self._recarregar_lista()

    # ------------------------------------------------------------------ motor
    def ligar_motor(self, motor, sessao_provider, cenas_provider=None) -> None:
        """Recebe o motor, a sessão ativa e (opcional) a cena aplicada."""
        self._motor = motor
        self._sessao_provider = sessao_provider
        self._cenas_provider = cenas_provider or (lambda: None)

    def _resumo_fonte(self) -> str:
        """O que está configurado para ir ao ar (da cena ativa)."""
        cena = self._cenas_provider() if hasattr(self, "_cenas_provider") else None
        if cena:
            partes = [f"Vídeo: {cena.get('fonte', 'monitor')}"]
            if cena.get("alvo"):
                partes.append(f"alvo: {str(cena.get('alvo'))[:50]}")
            partes.append(f"áudio: {cena.get('audio_label', 'mic + sistema')}")
            if cena.get("cam_sobre"):
                partes.append("câmera sobreposta incluída")
            return "Preset da cena '" + str(cena.get("nome", "")) + "': " +                 ", ".join(partes)
        return ("Preset: o da aba Gravação (sem cena ativa). "
                "Escolha uma cena na aba Cenas para controlar o que vai ao ar.")

    def _abrir_cenas(self) -> None:
        """Leva o usuário à aba Cenas — é lá que o preset se edita."""
        try:
            livro = self.GetParent()
            while livro is not None and not isinstance(livro, wx.Notebook):
                livro = livro.GetParent()
            if livro is not None:
                for i in range(livro.GetPageCount()):
                    if livro.GetPageText(i).lower().startswith("cen"):
                        livro.SetSelection(i)
                        self.speech.falar("Aba Cenas aberta", interrupt=True)
                        return
        except Exception:
            pass
        self.speech.falar("Não encontrei a aba Cenas", interrupt=True)

    # ------------------------------------------------------------------ lista
    def _anunciar_item(self) -> None:
        i = self.lista.GetFocusedItem()
        if 0 <= i < len(self._destinos):
            d = self._destinos[i]
            self.speech.falar(f"{d.get('nome', '')}, {d.get('url', '')}, "
                              f"{i + 1} de {len(self._destinos)}")

    def _item_atual(self) -> str:
        i = self.lista.GetFocusedItem()
        if i < 0 or i >= len(self._destinos):
            return ""
        d = self._destinos[i]
        return (f"{d.get('nome', '')} — {d.get('url', '')} — "
                f"{'ao vivo' if self._ativo else 'parado'}")

    def _recarregar_lista(self) -> None:
        self.lista.DeleteAllItems()
        for i, d in enumerate(self._destinos):
            self.lista.InsertItem(i, d.get("nome", f"Destino {i + 1}"))
            self.lista.SetItem(i, 1, d.get("url", ""))
        if not self._destinos:
            self.lista.InsertItem(0, t("transmission.noStream"))
            self.lista.SetItem(0, 1, "")

    def _aplicar_preset(self) -> None:
        chave = ["twitch", "youtube", "facebook", "custom"][
            self.escolha_preset.GetSelection()]
        if chave in PRESETS:
            self.campo_url.SetValue(PRESETS[chave])
            self.campo_chave.SetFocus()

    def _adicionar(self) -> None:
        url = self.campo_url.GetValue().strip()
        chave = self.campo_chave.GetValue().strip()
        if not url or url == "rtmp://":
            self.speech.falar("Informe a URL RTMP", interrupt=True)
            return
        completa = url + chave if chave and not url.endswith(chave) else url
        nome = self.escolha_preset.GetStringSelection()
        self._destinos.append({"nome": nome, "url": completa})
        self.cfg["rtmp"] = self._destinos
        self._recarregar_lista()
        self.campo_chave.SetValue("")
        self.Layout()
        self.speech.falar(f"Destino adicionado: {nome}", interrupt=True)

    def _remover(self) -> None:
        i = self.lista.GetFocusedItem()
        if 0 <= i < len(self._destinos):
            d = self._destinos.pop(i)
            self.cfg["rtmp"] = self._destinos
            self._recarregar_lista()
            self.Layout()
            self.speech.falar(f"Destino removido: {d.get('nome', '')}",
                              interrupt=True)

    # ------------------------------------------------------------------ live
    def _status(self) -> str:
        if self._ativo:
            return f"Ao vivo para {len(self._destinos)} destino(s)"
        return "Parado"

    def _nome_botao_live(self) -> str:
        return (t("transmission.stopStreaming") if self._ativo
                else t("transmission.startStreaming"))

    def _alternar_live(self) -> None:
        if self._ativo:
            self._parar_live()
        else:
            self._iniciar_live()

    def _iniciar_live(self) -> None:
        if not self._motor or not self._motor.disponivel:
            self.speech.falar("Motor indisponível", interrupt=True)
            return
        if not self._destinos:
            self.speech.falar("Adicione um destino RTMP primeiro", interrupt=True)
            return
        sessao = getattr(self, "_sessao_provider", lambda: None)()
        if sessao is None:
            self.speech.falar("Inicie a gravação primeiro", interrupt=True)
            return
        self._sessao = sessao
        ok, falhas = 0, []
        for d in self._destinos:
            try:
                self._motor.adicionar_rtmp(sessao, d["url"])
                ok += 1
            except Exception as e:
                falhas.append(f"{d.get('nome')}: {e}")
        self._ativo = ok > 0
        self.btn_ao_vivo.SetLabel(self._nome_botao_live())
        self.texto_status.SetLabel(self._status())
        self.Layout()
        if falhas:
            self.speech.falar(f"Ao vivo em {ok}, falhou: {'; '.join(falhas)}",
                              interrupt=True)
        else:
            self.speech.falar(f"Ao vivo em {ok} destino(s)", interrupt=True)

    def _parar_live(self) -> None:
        sessao = self._sessao or getattr(self, "_sessao_provider", lambda: None)()
        for d in self._destinos:
            try:
                self._motor.remover_rtmp(sessao, d["url"])
            except Exception:
                pass
        self._ativo = False
        self.btn_ao_vivo.SetLabel(self._nome_botao_live())
        self.texto_status.SetLabel(self._status())
        self.Layout()
        self.speech.falar("Transmissão encerrada", interrupt=True)
