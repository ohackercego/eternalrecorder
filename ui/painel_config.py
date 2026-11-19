"""Aba Configurações: qualidade, microfone, atalhos, pasta, idioma, versão.

Atalhos: cada linha tem um BOTÃO que abre uma janela para pressionar a
combinação — antes era um campo de texto onde o usuário tinha que digitar
"Control+Shift+R" letra por letra, o que ninguém acerta.

Idioma: seletor com os 25 locales, aplicado na hora.
"""
from __future__ import annotations

from pathlib import Path

import wx

from ui import accessible as a11y
from ui.i18n import t
from ui.dialogo_atalho import DialogoAtalho

FPS = ["24", "30", "60"]
RESOLUCOES = ["source", "1920x1080", "1280x720", "854x480"]
BITRATES_V = ["1000", "2500", "4000", "6000", "8000"]
BITRATES_A = ["96", "128", "192", "256", "320"]
# Ganho em dB. O PRIMEIRO item é "seguir o sistema": volume 1.0 (o mesmo que
# o Windows entrega), sem multiplicação. Era o pedido do usuário: o ganho
# fixo LIMITA o áudio — quem ajusta o volume no Windows espera que ele mande.
GANHOS = ["seguir o sistema (recomendado)", "0", "6", "12", "18", "24"]

NOMES_IDIOMA = {
    "pt-br": "Português (Brasil)", "en": "English", "es": "Español",
    "fr": "Français", "de": "Deutsch", "it": "Italiano", "ja": "日本語",
    "ko": "한국어", "zh": "中文 (简体)", "zh-TW": "中文 (繁體)",
    "zh-yue": "廣東話", "ru": "Русский", "uk": "Українська",
    "nl": "Nederlands", "tr": "Türkçe", "ar": "العربية", "he": "עברית",
    "hi": "हिन्दी", "th": "ไทย", "vi": "Tiếng Việt", "af": "Afrikaans",
    "el": "Ελληνικά", "ca": "Català", "eo": "Esperanto", "bo": "བོད་ཡིག",
}


class PainelConfiguracoes(wx.Panel):
    def __init__(self, pai: wx.Window, speech, config: dict) -> None:
        super().__init__(pai)
        self.speech = speech
        self.cfg = config
        self._atalhos: dict[str, str] = dict(config.get("shortcuts") or {})
        self._botoes_atalho: dict[str, wx.Button] = {}
        self.ao_mudar_idioma = None

        s = wx.BoxSizer(wx.VERTICAL)

        # ── qualidade ──
        caixa_q = wx.StaticBox(self, -1, t("settings.recordingQuality"))
        box_q = wx.StaticBoxSizer(caixa_q, wx.VERTICAL)
        grade = wx.FlexGridSizer(6, 2, 8, 12)
        grade.AddGrowableCol(1, 1)

        self.escolha_fps = self._linha(caixa_q, grade, t("settings.recFps"),
                                       FPS, str(self.cfg.get("fps", "30")))
        self.escolha_res = self._linha(
            caixa_q, grade, t("settings.recResolution"),
            [t("settings.recResolutionSource")] + RESOLUCOES[1:],
            self.cfg.get("resolution", "source"))
        self.escolha_bv = self._linha(caixa_q, grade,
                                      t("settings.recVideoBitrate"), BITRATES_V,
                                      str(self.cfg.get("videoBitrate", "2500")))
        self.escolha_ba = self._linha(caixa_q, grade,
                                      t("settings.recAudioBitrate"), BITRATES_A,
                                      str(self.cfg.get("audioBitrate", "192")))
        self.escolha_mic = self._linha(caixa_q, grade, t("settings.micGain"),
                                       GANHOS, str(self.cfg.get("micGain", "")))
        self.escolha_sys = self._linha(caixa_q, grade, t("settings.sysGain"),
                                       GANHOS, str(self.cfg.get("sysGain", "")))
        box_q.Add(grade, 1, wx.EXPAND | wx.ALL, 10)
        s.Add(box_q, 0, wx.EXPAND | wx.ALL, 10)

        # ── pasta ──
        caixa_p = wx.StaticBox(self, -1, t("settings.folderLabel"))
        box_p = wx.StaticBoxSizer(caixa_p, wx.VERTICAL)
        linha_p = wx.BoxSizer(wx.HORIZONTAL)
        # mostra a pasta EFETIVA: se a config está vazia, grava em
        # Vídeos do usuário — o campo precisa mostrar isso, não vazio
        _pasta_cfg = self.cfg.get("folder", "")
        _pasta_efetiva = _pasta_cfg or str(Path.home() / "Videos")
        # ── POR QUE NÃO wx.TE_READONLY ──
        # O TextCtrl com TE_READONLY recebe foco mas VÁRIOS leitores de tela
        # o pulam na navegação por Tab (não é editável, não é "campo"). O
        # usuário relatou exatamente isso: "a caixa somente leitura não
        # aparece dando tab até ela". A solução é um campo editável por
        # baixo com SetEditable(False): o controle é anunciado como campo de
        # texto normal, entra no ciclo de Tab, e o Windows bloqueia a edição.
        self.texto_pasta = wx.TextCtrl(caixa_p, value=_pasta_efetiva)
        self.texto_pasta.SetEditable(False)
        # cor de leitura (não parece editável)
        try:
            self.texto_pasta.SetBackgroundColour(
                wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE))
        except Exception:
            pass
        # O VALOR vai no nome acessível: leitores de tela só anunciam
        # consistentemente o que está no nome. "somente leitura" entra junto
        # (o usuário precisa saber que não edita ali; muda pelo botão).
        a11y.aplicar(self.texto_pasta, a11y.CampoAcessivel(
            self.texto_pasta, t("settings.folderLabel"),
            valor_fn=lambda: (
                f"{self.texto_pasta.GetValue() or '(pasta padrão)'}. "
                f"Somente leitura. Para mudar, use o botão de escolher pasta")))
        linha_p.Add(self.texto_pasta, 1, wx.RIGHT, 8)
        # O BOTÃO carrega a pasta atual no nome: "A pasta atual é X; clique
        # aqui para escolher uma nova". O campo read-only é focável, mas
        # alguns leitores pulam campos não-editáveis — o botão NUNCA é pulado,
        # então o usuário sempre ouve onde está gravando (sugestão dele).
        self.btn_pasta = a11y.botao(
            caixa_p, self._nome_btn_pasta,
            lambda e: self._escolher_pasta(), self._nome_btn_pasta)
        linha_p.Add(self.btn_pasta, 0, wx.RIGHT, 8)
        self.btn_pasta_padrao = a11y.botao(
            caixa_p, lambda: t("settings.folderReset"),
            lambda e: self._restaurar_pasta(), lambda: t("settings.folderReset"))
        linha_p.Add(self.btn_pasta_padrao, 0)
        box_p.Add(linha_p, 0, wx.EXPAND | wx.ALL, 10)
        self.texto_dica_pasta = wx.StaticText(caixa_p,
                                              label=t("settings.folderHint"))
        box_p.Add(self.texto_dica_pasta, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        s.Add(box_p, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # ORDEM DE TAB: o campo da pasta tem que vir ANTES dos botões, senão
        # o leitor "pula direto para os botões" sem nunca falar a pasta
        # (relatado). MoveBeforeInTabOrder com o botão como referência.
        try:
            self.texto_pasta.MoveBeforeInTabOrder(self.btn_pasta)
        except Exception:
            pass

        # ── atalhos: um botão por atalho ──
        caixa_a = wx.StaticBox(self, -1, t("settings.shortcuts"))
        box_a = wx.StaticBoxSizer(caixa_a, wx.VERTICAL)
        for chave, rotulo in (
            ("start", t("settings.shortcutStart")),
            ("stop", t("settings.shortcutStop")),
            ("pause", t("settings.shortcutPause")),
            ("mute", t("settings.shortcutMute")),
            ("toggleAudio", t("settings.shortcutToggleAudio")),
            ("toggleWindow", t("settings.shortcutToggleWindow")),
        ):
            linha_a = wx.BoxSizer(wx.HORIZONTAL)
            linha_a.Add(a11y.rotulo(caixa_a, lambda r=rotulo: r), 1,
                        wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            btn = a11y.botao(
                caixa_a,
                lambda k=chave: self._texto_botao_atalho(k),
                lambda e, k=chave, r=rotulo: self._definir_atalho(k, r),
                lambda k=chave, r=rotulo: self._nome_botao_atalho(k, r),
            )
            self._botoes_atalho[chave] = btn
            linha_a.Add(btn, 0)
            box_a.Add(linha_a, 0, wx.EXPAND | wx.ALL, 6)
        s.Add(box_a, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # ── idioma ──
        linha_i = wx.BoxSizer(wx.HORIZONTAL)
        linha_i.Add(a11y.rotulo(self, lambda: t("settings.language")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        from ui import i18n as modulo_i18n
        self._codigos = modulo_i18n.disponiveis()
        self.escolha_idioma = wx.Choice(
            self, choices=[NOMES_IDIOMA.get(c, c) for c in self._codigos])
        atual = self.cfg.get("idioma") or modulo_i18n.idioma()
        if atual in self._codigos:
            self.escolha_idioma.SetSelection(self._codigos.index(atual))
        self.escolha_idioma.Bind(wx.EVT_CHOICE, lambda e: self._mudar_idioma())
        a11y.aplicar(self.escolha_idioma, a11y.EscolhaAcessivel(
            self.escolha_idioma, t("settings.language")))
        linha_i.Add(self.escolha_idioma, 1, wx.RIGHT, 8)
        s.Add(linha_i, 0, wx.EXPAND | wx.ALL, 10)

        # ── comportamento e versão ──
        linha_b = wx.BoxSizer(wx.HORIZONTAL)
        linha_b.Add(a11y.rotulo(self, lambda: t("settings.closeBehavior")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_fechar = wx.Choice(self, choices=[
            t("settings.closeBehaviorExit"), t("settings.closeBehaviorTray")])
        self.escolha_fechar.SetSelection(
            1 if self.cfg.get("closeBehavior", "tray") == "tray" else 0)
        a11y.aplicar(self.escolha_fechar, a11y.EscolhaAcessivel(
            self.escolha_fechar, t("settings.closeBehavior")))
        # ESTE é o controle do fechar-para-bandeja — não há checkbox além dele.
        # Ele existia mas ninguém lia o valor: era um controle órfão.
        self.escolha_fechar.Bind(
            wx.EVT_CHOICE,
            lambda e: self._salvar_close_behavior(
                self.escolha_fechar.GetSelection()))
        linha_b.Add(self.escolha_fechar, 1)
        s.Add(linha_b, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        linha_v = wx.BoxSizer(wx.HORIZONTAL)
        linha_v.Add(a11y.rotulo(self, lambda: t("settings.version")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.texto_versao = wx.StaticText(self,
                                          label=self.cfg.get("version", "2.1.0"))
        linha_v.Add(self.texto_versao, 1)
        s.Add(linha_v, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.btn_salvar = a11y.botao(
            self, lambda: t("config.salvar"), lambda e: self._salvar(),
            lambda: t("config.salvarDica"))
        s.Add(self.btn_salvar, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(s)

    # ------------------------------------------------------------------ helpers
    def _linha(self, pai, grade, rotulo: str, opcoes: list[str],
               valor: str) -> wx.Choice:
        grade.Add(a11y.rotulo(pai, lambda r=rotulo: r), 0,
                  wx.ALIGN_CENTER_VERTICAL)
        c = wx.Choice(pai, choices=opcoes)
        c.SetSelection(opcoes.index(valor) if valor in opcoes else 0)
        a11y.aplicar(c, a11y.EscolhaAcessivel(c, rotulo))
        grade.Add(c, 1, wx.EXPAND)
        return c

    # ------------------------------------------------------------------ atalhos
    def _texto_botao_atalho(self, chave: str) -> str:
        valor = self._atalhos.get(chave, "")
        return valor if valor else "Definir…"

    def _nome_botao_atalho(self, chave: str, rotulo: str) -> str:
        valor = self._atalhos.get(chave, "")
        if valor:
            return f"{rotulo}: {valor}. Ativar para alterar"
        return f"{rotulo}: sem atalho. Ativar para definir"

    def _definir_atalho(self, chave: str, rotulo: str) -> None:
        novo = DialogoAtalho.pedir(self, self.speech, rotulo,
                                   self._atalhos.get(chave, ""))
        if novo is None:
            return
        for outra, valor in list(self._atalhos.items()):
            if outra != chave and valor and valor == novo:
                dlg = wx.MessageDialog(
                    self, f"Este atalho já está em «{outra}». Substituir?",
                    "Atalho duplicado", wx.YES_NO | wx.ICON_WARNING)
                if dlg.ShowModal() != wx.YES:
                    dlg.Destroy()
                    return
                dlg.Destroy()
                self._atalhos[outra] = ""
                btn = self._botoes_atalho.get(outra)
                if btn:
                    btn.SetLabel("Definir…")
        self._atalhos[chave] = novo
        btn = self._botoes_atalho.get(chave)
        if btn:
            btn.SetLabel(novo or "Definir…")
        self.Layout()
        self.speech.falar(f"Atalho {rotulo}: {novo or 'removido'}",
                          interrupt=True)

    # ------------------------------------------------------------------ idioma
    def _mudar_idioma(self) -> None:
        i = self.escolha_idioma.GetSelection()
        if i < 0:
            return
        codigo = self._codigos[i]
        self.cfg["idioma"] = codigo
        from ui import i18n as modulo_i18n
        modulo_i18n.carregar(codigo)
        nome = NOMES_IDIOMA.get(codigo, codigo)
        self.speech.falar(f"Idioma: {nome}", interrupt=True)
        cb = getattr(self, "ao_mudar_idioma", None)
        if callable(cb):
            cb(codigo)

    # ------------------------------------------------------------------ pasta
    def _nome_btn_pasta(self) -> str:
        pasta = self.texto_pasta.GetValue() or "(pasta padrão)"
        return (f"A pasta atual é {pasta}. "
                f"Clique aqui para escolher uma nova pasta")

    def _salvar_close_behavior(self, selecao: int) -> None:
        """'Sair' ou 'Ir para a bandeja' — o que o Alt-F4/X vai fazer."""
        valor = "tray" if selecao == 1 else "exit"
        self.cfg["closeBehavior"] = valor
        try:
            from engine.config import salvar
            salvar(self.cfg)
        except Exception:
            pass
        self.speech.falar(
            "Ao fechar: ir para a bandeja" if selecao == 1
            else "Ao fechar: sair do aplicativo", interrupt=True)

    def _salvar_flag(self, chave: str, valor) -> None:
        """Grava uma flag booleana na config (usado pelas caixas da aba)."""
        self.cfg[chave] = bool(valor)
        try:
            from engine.config import salvar
            salvar(self.cfg)
        except Exception:
            pass
        self.speech.falar(
            "Ativado" if valor else "Desativado", interrupt=True)

    def _escolher_pasta(self) -> None:
        atual = self.texto_pasta.GetValue() or str(Path.home() / "Videos")
        with wx.DirDialog(self, t("settings.folderLabel"), atual,
                          wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.texto_pasta.SetValue(dlg.GetPath())
                self.texto_dica_pasta.SetLabel(t("settings.folderSaved"))
                # anuncia a pasta NOVA por cima (o nome do botão também
                # muda, pois _nome_btn_pasta lê o campo na hora)
                self.speech.falar(
                    f"Pasta alterada. A pasta atual é {dlg.GetPath()}",
                    interrupt=True)
                self.Layout()

    def _restaurar_pasta(self) -> None:
        self.texto_pasta.SetValue(str(Path.home() / "Videos"))
        self.texto_dica_pasta.SetLabel(t("settings.folderHint"))
        self.Layout()
        self.speech.falar("Pasta padrão restaurada")

    # ------------------------------------------------------------------ salvar
    def _salvar(self) -> None:
        self.cfg.update({
            "fps": self.escolha_fps.GetStringSelection(),
            "resolution": RESOLUCOES[max(0, self.escolha_res.GetSelection())],
            "videoBitrate": self.escolha_bv.GetStringSelection(),
            "audioBitrate": self.escolha_ba.GetStringSelection(),
            # grava o dB, nunca o texto da opção ("seguir o sistema...")
            "micGain": "" if self.escolha_mic.GetSelection() == 0
                       else GANHOS[self.escolha_mic.GetSelection()],
            "sysGain": "" if self.escolha_sys.GetSelection() == 0
                       else GANHOS[self.escolha_sys.GetSelection()],
            "folder": self.texto_pasta.GetValue(),
            "closeBehavior": ("tray" if self.escolha_fechar.GetSelection() == 1
                              else "exit"),
            "shortcuts": dict(self._atalhos),
        })
        try:
            from engine.config import salvar
            salvar(self.cfg)
            self.speech.falar("Configurações salvas", interrupt=True)
        except Exception as e:
            self.speech.falar(f"Erro ao salvar: {e}", interrupt=True)
