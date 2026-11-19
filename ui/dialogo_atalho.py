"""Diálogo para definir UM atalho, capturando a combinação pressionada.

Antes o campo de atalho era um `wx.TextCtrl` onde o usuário precisava digitar
o texto ("Control+Shift+R") — impossível de acertar sem saber a sintaxe. Agora
é um botão que abre esta janela: o usuário aperta a combinação e ela aparece.

Acessibilidade: o campo é `ROLE_SYSTEM_HOTKEYFIELD` e o anúncio do atalho
capturado é falado uma vez, pelo `Speech`.
"""
from __future__ import annotations

import wx

from ui import accessible as a11y


def _nome_tecla(k: int) -> str | None:
    mapa = {
        wx.WXK_F1: "F1", wx.WXK_F2: "F2", wx.WXK_F3: "F3", wx.WXK_F4: "F4",
        wx.WXK_F5: "F5", wx.WXK_F6: "F6", wx.WXK_F7: "F7", wx.WXK_F8: "F8",
        wx.WXK_F9: "F9", wx.WXK_F10: "F10", wx.WXK_F11: "F11",
        wx.WXK_F12: "F12", wx.WXK_SPACE: "Space", wx.WXK_TAB: "Tab",
        wx.WXK_RETURN: "Enter", wx.WXK_ESCAPE: "Escape",
        wx.WXK_HOME: "Home", wx.WXK_END: "End", wx.WXK_PAGEUP: "PageUp",
        wx.WXK_PAGEDOWN: "PageDown", wx.WXK_UP: "Up", wx.WXK_DOWN: "Down",
        wx.WXK_LEFT: "Left", wx.WXK_RIGHT: "Right",
        wx.WXK_INSERT: "Insert", wx.WXK_DELETE: "Delete",
    }
    if k in mapa:
        return mapa[k]
    if 65 <= k <= 90:
        return chr(k)
    if 48 <= k <= 57:
        return chr(k)
    return None


class DialogoAtalho(wx.Dialog):
    """Captura uma combinação de teclas para um atalho."""

    def __init__(self, pai: wx.Window, speech, rotulo: str,
                 atual: str = "") -> None:
        super().__init__(pai, title=f"Definir atalho — {rotulo}",
                         size=(460, 300),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.speech = speech
        self.valor = atual or ""
        self._rotulo = rotulo

        s = wx.BoxSizer(wx.VERTICAL)

        s.Add(a11y.rotulo(self, lambda: rotulo), 0, wx.ALL, 12)

        self.texto_instrucao = wx.StaticText(
            self, label="Pressione a combinação desejada "
                        "(ex.: Ctrl+Shift+R). Esc cancela.")
        s.Add(self.texto_instrucao, 0, wx.LEFT | wx.RIGHT, 12)

        # campo que recebe a tecla e mostra a combinação
        self.campo = wx.TextCtrl(self, value=self.valor, style=wx.TE_READONLY)
        self.campo.SetFont(self.campo.GetFont().Bold())
        a11y.aplicar(self.campo, a11y.ControleAcessivel(
            self.campo, lambda: f"Atalho para {rotulo}",
            wx.ROLE_SYSTEM_HOTKEYFIELD,
            lambda: self.campo.GetValue()))
        self.campo.Bind(wx.EVT_KEY_DOWN, self._ao_tecla)
        s.Add(self.campo, 0, wx.EXPAND | wx.ALL, 12)

        self.texto_aviso = a11y.rotulo(self, lambda: "")
        s.Add(self.texto_aviso, 0, wx.LEFT | wx.RIGHT, 12)

        linha = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_limpar = a11y.botao(
            self, lambda: t("atalho.limpar"), lambda e: self._limpar(),
            lambda: t("atalho.limparDica"))
        linha.Add(self.btn_limpar, 1, wx.RIGHT, 8)
        self.btn_ok = a11y.botao(
            self, lambda: t("atalho.salvar"), lambda e: self._confirmar(),
            lambda: t("atalho.salvarDica"))
        linha.Add(self.btn_ok, 1, wx.RIGHT, 8)
        self.btn_cancelar = a11y.botao(
            self, lambda: t("atalho.cancelar"), lambda e: self._cancelar(),
            lambda: t("atalho.cancelarDica"))
        linha.Add(self.btn_cancelar, 1)
        s.Add(linha, 0, wx.EXPAND | wx.ALL, 12)

        self.SetSizer(s)
        self.campo.SetFocus()
        self.CentreOnParent()

    # ------------------------------------------------------------------ teclas
    def _ao_tecla(self, ev) -> None:
        k = getattr(ev, "m_keyCode", 0) or ev.GetKeyCode()
        if k in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT,
                 wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT, 0):
            ev.Skip()
            return
        if k == wx.WXK_ESCAPE:
            self._cancelar()
            return

        ctrl = getattr(ev, "m_controlDown", False) or ev.ControlDown()
        alt = getattr(ev, "m_altDown", False) or ev.AltDown()
        shift = getattr(ev, "m_shiftDown", False) or ev.ShiftDown()

        nome = _nome_tecla(k)
        if nome is None:
            self.texto_aviso.SetLabel("Tecla não suportada")
            self.Layout()
            return

        # atalho sem modificador só é aceito para F1..F12 (evita capturar
        # letras soltas, que disparariam ao digitar em qualquer campo)
        if not (ctrl or alt or shift) and not nome.startswith("F"):
            self.texto_aviso.SetLabel(
                "Use Ctrl, Alt ou Shift junto — ou uma tecla F1 a F12.")
            self.Layout()
            self.speech.falar("Adicione Control, Alt ou Shift")
            return

        partes = []
        if ctrl:
            partes.append("Control")
        if alt:
            partes.append("Alt")
        if shift:
            partes.append("Shift")
        partes.append(nome)
        self.valor = "+".join(partes)
        self.campo.SetValue(self.valor)
        self.texto_aviso.SetLabel("")
        self.Layout()
        self.speech.falar(self.valor)
        self._conflito = None

    def _limpar(self) -> None:
        self.valor = ""
        self.campo.SetValue("")
        self.speech.falar("Atalho removido")
        self.campo.SetFocus()

    def _confirmar(self) -> None:
        if not self.valor:
            self.texto_aviso.SetLabel("Pressione uma combinação antes de salvar.")
            self.Layout()
            return
        self.EndModal(wx.ID_OK)

    def _cancelar(self) -> None:
        self.EndModal(wx.ID_CANCEL)

    # ------------------------------------------------------------------ api
    @staticmethod
    def pedir(pai: wx.Window, speech, rotulo: str,
              atual: str = "") -> str | None:
        """Abre o diálogo. Devolve o atalho ou None se cancelado."""
        dlg = DialogoAtalho(pai, speech, rotulo, atual)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                return dlg.valor
            return None
        finally:
            dlg.Destroy()
