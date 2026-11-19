"""Aba Cenas: presets completos de gravação, com troca ao vivo e hotkeys.

CADA CENA É UM PRESET — não só "qual fonte está ativa", mas TODO o que a
gravação usa:

    fonte de vídeo:  monitor | janela | camera | sem vídeo (somente áudio)
    alvo:            qual monitor / janela / câmera
    áudio:           none | mic | system | both
    câmera sobreposta: (nos modos monitor/janela) canto + tamanho

Isso atende o pedido: "a cena pode ter um preset/configuração do que quiser,
como microfone, áudio do sistema, tela cheia ou janela, câmera, somente
áudio, somente câmera, usar câmera na gravação tela ou janela".

HOTKEYS 1-9 E 0
---------------
Teclas 1..9 ativam as cenas 1..9 e 0 ativa a 10ª — direto do pedido:
"vai do 1 ao 10, que na tecla do teclado 0 é o 10 e 1 é 1, em diante; isso
ativa a cena 1, 2 etc". São atalhos GLOBAIS (funcionam com o app minimizado),
registrados com RegisterHotKey do Windows — o AcceleratorTable do wx só
funciona com a janela focada, inútil durante uma gravação.

POR QUE AS CENAS NÃO ERAM APLICADAS (bug relatado)
--------------------------------------------------
O painel antigo chamava `getattr(self, "ao_ativar", None)` — e `ao_ativar`
nunca existia: ninguém ligava o callback. A cena "ativava" (falava, marcava
status) e nada acontecia na gravação. Agora a Janela liga `ao_aplicar` na
criação e o painel de gravação aplica de verdade: durante gravação via
`motor.trocar_cena` (o arquivo continua), fora de gravação via flags que a
próxima gravação usa.
"""
from __future__ import annotations

import uuid

import wx

from ui import accessible as a11y
from ui.i18n import t

# As listas são FUNÇÕES: o rótulo depende do idioma carregado no momento.
# Os VALORES canônicos ficam separados (o que é salvo na cena não muda).
MODOS_VIDEO_VALORES = ["monitor", "janela", "camera", "none"]
MODOS_VIDEO_ROTULOS = lambda: [
    t("cenas.fonteVideo"), t("cenas.alvo"), t("recorder.cameraOnlyMode"),
    t("cenas.semVideo")]
MODOS_AUDIO_VALORES = ["none", "mic", "system", "both"]
MODOS_AUDIO_ROTULOS = lambda: [
    t("cenas.semAudio"), t("cenas.microfone2"), t("cenas.audioSistema"),
    t("cenas.micESistema")]
CANTOS_VALORES = ["sup_esq", "sup_dir", "inf_esq", "inf_dir"]
CANTOS_ROTULOS = lambda: [
    t("cenas.cantoSupEsq"), t("cenas.cantoSupDir"), t("cenas.cantoInfEsq"),
    t("cenas.cantoInfDir")]
TAMANHOS_VALORES = ["pequena", "média", "grande"]
TAMANHOS_ROTULOS = lambda: [
    t("cenas.tamPequena"), t("cenas.tamMedia"), t("cenas.tamGrande")]


class PainelCenas(wx.Panel):
    def __init__(self, pai: wx.Window, speech, config: dict, motor=None) -> None:
        super().__init__(pai)
        self.speech = speech
        self.cfg = config
        self.motor = motor
        self.cenas: list[dict] = list(config.get("scenes", []))
        self._ativa_idx = -1
        # callback ligado pela Janela: aplica a cena no painel de gravação
        self.ao_aplicar = None

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(a11y.rotulo(
            self, lambda: t("scenes.hint")), 0, wx.ALL, 10)

        caixa = wx.StaticBoxSizer(wx.VERTICAL, self, t("tabs.scenes"))
        # ListaAcessivel: nome só no childId 0. Sobrescrever todos os childIds
        # faz o leitor entrar em laço e a janela TRAVAR ao descer a lista.
        self.lista = a11y.lista(self, lambda: "Cenas")
        self.lista.InsertColumn(0, t("cenas.colNome"), width=180)
        self.lista.InsertColumn(1, t("cenas.colPreset"), width=430)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._ativar())
        self.lista.Bind(wx.EVT_LIST_ITEM_FOCUSED, lambda e: self._anunciar_item())
        caixa.Add(self.lista, 1, wx.EXPAND | wx.ALL, 8)

        self.texto_dica = wx.StaticText(
            self, label=t("cenas.menuHint"))
        caixa.Add(self.texto_dica, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        sizer.Add(caixa, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # ── editor do preset ──
        # Os controles são filhos do StaticBox (não do painel): é o que o wx
        # exige para o leitor agrupar os campos sob o rótulo do grupo.
        caixa_ed = wx.StaticBox(self, -1, "Preset da cena")
        editor = wx.StaticBoxSizer(caixa_ed, wx.VERTICAL)

        l_nome = wx.BoxSizer(wx.HORIZONTAL)
        l_nome.Add(a11y.rotulo(caixa_ed, lambda: t("cenas.nomeCena")), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.campo_nome = wx.TextCtrl(caixa_ed, value="")
        a11y.aplicar(self.campo_nome, a11y.CampoAcessivel(
            self.campo_nome, t("cenas.nomeCena")))
        l_nome.Add(self.campo_nome, 1)
        editor.Add(l_nome, 0, wx.EXPAND | wx.ALL, 6)

        l_video = wx.BoxSizer(wx.HORIZONTAL)
        l_video.Add(a11y.rotulo(caixa_ed, lambda: t("cenas.video")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_fonte = wx.Choice(caixa_ed, choices=MODOS_VIDEO_ROTULOS())
        self.escolha_fonte.SetSelection(0)
        a11y.aplicar(self.escolha_fonte, a11y.EscolhaAcessivel(
            self.escolha_fonte, "Fonte de vídeo da cena"))
        l_video.Add(self.escolha_fonte, 0, wx.RIGHT, 8)
        self.escolha_alvo = wx.Choice(caixa_ed, choices=["—"])
        a11y.aplicar(self.escolha_alvo, a11y.EscolhaAcessivel(
            self.escolha_alvo, "Alvo (monitor, janela ou câmera)"))
        l_video.Add(self.escolha_alvo, 1)
        editor.Add(l_video, 0, wx.EXPAND | wx.ALL, 6)

        l_audio = wx.BoxSizer(wx.HORIZONTAL)
        l_audio.Add(a11y.rotulo(caixa_ed, lambda: t("cenas.audio")), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_audio = wx.Choice(caixa_ed, choices=MODOS_AUDIO_ROTULOS())
        self.escolha_audio.SetSelection(3)     # mic + sistema é o comum
        a11y.aplicar(self.escolha_audio, a11y.EscolhaAcessivel(
            self.escolha_audio, "Áudio da cena"))
        l_audio.Add(self.escolha_audio, 1)
        editor.Add(l_audio, 0, wx.EXPAND | wx.ALL, 6)

        # câmera sobreposta (só faz sentido com monitor/janela)
        self.chk_cam_sobre = a11y.caixa(
            caixa_ed, lambda: "Usar câmera sobreposta na gravação")
        editor.Add(self.chk_cam_sobre, 0, wx.ALL, 6)
        l_sobre = wx.BoxSizer(wx.HORIZONTAL)
        l_sobre.Add(a11y.rotulo(caixa_ed, lambda: "Canto da câmera"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_canto = wx.Choice(caixa_ed, choices=CANTOS_ROTULOS())
        self.escolha_canto.SetSelection(1)
        a11y.aplicar(self.escolha_canto, a11y.EscolhaAcessivel(
            self.escolha_canto, "Canto da câmera sobreposta"))
        l_sobre.Add(self.escolha_canto, 1, wx.RIGHT, 8)
        l_sobre.Add(a11y.rotulo(caixa_ed, lambda: "Tamanho"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.escolha_tam = wx.Choice(caixa_ed, choices=TAMANHOS_ROTULOS())
        self.escolha_tam.SetSelection(1)
        a11y.aplicar(self.escolha_tam, a11y.EscolhaAcessivel(
            self.escolha_tam, "Tamanho da câmera sobreposta"))
        l_sobre.Add(self.escolha_tam, 1)
        editor.Add(l_sobre, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(editor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # ── botões ──
        linha3 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_nova = a11y.botao(
            self, lambda: "Adicionar cena", lambda e: self._nova(),
            lambda: "Adicionar cena com o preset acima")
        linha3.Add(self.btn_nova, 1, wx.RIGHT, 8)
        self.btn_atualizar = a11y.botao(
            self, lambda: "Salvar no selecionado",
            lambda e: self._atualizar(),
            lambda: "Salvar o preset na cena selecionada")
        linha3.Add(self.btn_atualizar, 1, wx.RIGHT, 8)
        self.btn_ativar = a11y.botao(
            self, lambda: "Ativar cena", lambda e: self._ativar(),
            lambda: "Ativar cena selecionada")
        linha3.Add(self.btn_ativar, 1, wx.RIGHT, 8)
        self.btn_excluir = a11y.botao(
            self, lambda: t("scenes.deleteScene"), lambda e: self._excluir(),
            lambda: t("scenes.deleteScene"))
        linha3.Add(self.btn_excluir, 1)
        sizer.Add(linha3, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.texto_status = a11y.rotulo(self, lambda: self._status())
        sizer.Add(self.texto_status, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(sizer)
        self.escolha_fonte.Bind(wx.EVT_CHOICE, lambda e: self._carregar_alvos())
        self.chk_cam_sobre.Bind(wx.EVT_CHECKBOX, lambda e: self._mostrar_sobre())
        self._carregar_alvos()
        self._recarregar()

    # ---------------------------------------------------------------- alvos
    def _carregar_alvos(self) -> None:
        modo = self.escolha_fonte.GetSelection()
        if modo == 3:                       # sem vídeo
            self.escolha_alvo.Set(["—"])
            self.escolha_alvo.Enable(False)
            self._mostrar_sobre()
            return
        self.escolha_alvo.Enable(True)
        if not self.motor or not self.motor.disponivel:
            self.escolha_alvo.Set(["motor indisponível"])
            return
        try:
            if modo == 0:                   # monitor
                itens = [f"Monitor {i + 1}: {m['largura']}x{m['altura']}"
                         for i, m in enumerate(self.motor.monitores())]
            elif modo == 1:                 # janela
                itens = [j["titulo"][:70] for j in self.motor.janelas()]
            else:                           # câmera
                itens = [c["nome"] for c in self.motor.cameras()]
        except Exception as e:
            itens = [f"erro: {e}"]
        self.escolha_alvo.Set(itens or ["—"])
        if itens:
            self.escolha_alvo.SetSelection(0)
        self._mostrar_sobre()

    def _mostrar_sobre(self) -> None:
        """Câmera sobreposta só tem sentido com monitor ou janela."""
        modo = self.escolha_fonte.GetSelection()
        permitir = modo in (0, 1)
        self.chk_cam_sobre.Enable(permitir)
        self.escolha_canto.Enable(permitir and self.chk_cam_sobre.GetValue())
        self.escolha_tam.Enable(permitir and self.chk_cam_sobre.GetValue())

    # ---------------------------------------------------------------- dados
    def _anunciar_item(self) -> None:
        i = self.lista.GetFocusedItem()
        if 0 <= i < len(self.cenas):
            c = self.cenas[i]
            self.speech.falar(
                f"{i + 1}: {c['nome']}. {self._resumo(c)}, "
                f"{i + 1} de {len(self.cenas)}")

    def _resumo(self, c: dict) -> str:
        partes = [f"vídeo {c.get('fonte', 'nenhum')}"]
        if c.get("alvo"):
            partes.append(str(c["alvo"]))
        partes.append(f"áudio {c.get('audio_label', 'mic + sistema')}")
        if c.get("cam_sobre"):
            partes.append("câmera sobreposta")
        return ", ".join(partes)

    def _status(self) -> str:
        if self._ativa_idx >= 0 and self._ativa_idx < len(self.cenas):
            return (f"Cena ativa: {self._ativa_idx + 1} — "
                    f"{self.cenas[self._ativa_idx]['nome']}")
        return "Nenhuma cena ativa"

    def _preset_do_editor(self) -> dict:
        modo = self.escolha_fonte.GetSelection()
        sel_aud = self.escolha_audio.GetSelection()
        return {
            "id": uuid.uuid4().hex[:8],
            "fonte": MODOS_VIDEO_VALORES[modo],
            "alvo": self.escolha_alvo.GetStringSelection(),
            "indice": max(0, self.escolha_alvo.GetSelection()),
            "audio": MODOS_AUDIO_VALORES[sel_aud],
            "audio_label": MODOS_AUDIO_ROTULOS()[sel_aud],
            "cam_sobre": bool(self.chk_cam_sobre.GetValue()) and modo in (0, 1),
            "canto": CANTOS_VALORES[self.escolha_canto.GetSelection()],
            "tamanho": TAMANHOS_VALORES[self.escolha_tam.GetSelection()],
        }

    def _carregar_editor(self, c: dict) -> None:
        """Preenche o editor com o preset da cena (para editar)."""
        self.campo_nome.SetValue(c.get("nome", ""))
        fonte = c.get("fonte", "monitor")
        self.escolha_fonte.SetSelection(
            MODOS_VIDEO_VALORES.index(fonte)
            if fonte in MODOS_VIDEO_VALORES else 0)
        self._carregar_alvos()
        alvo = str(c.get("alvo", ""))
        for i, it in enumerate(self.escolha_alvo.GetItems()):
            if it[:70] == alvo[:70]:
                self.escolha_alvo.SetSelection(i)
                break
        audio_v = c.get("audio", "both")
        self.escolha_audio.SetSelection(
            MODOS_AUDIO_VALORES.index(audio_v)
            if audio_v in MODOS_AUDIO_VALORES else 3)
        self.chk_cam_sobre.SetValue(bool(c.get("cam_sobre")))
        canto = c.get("canto", CANTOS_VALORES[1])
        self.escolha_canto.SetSelection(
            CANTOS_VALORES.index(canto) if canto in CANTOS_VALORES else 1)
        tam = c.get("tamanho", TAMANHOS_VALORES[1])
        self.escolha_tam.SetSelection(
            TAMANHOS_VALORES.index(tam) if tam in TAMANHOS_VALORES else 1)
        self._mostrar_sobre()

    def _recarregar(self) -> None:
        self.lista.DeleteAllItems()
        for i, c in enumerate(self.cenas):
            nome = c.get("nome", f"Cena {i + 1}")
            # hotkey é 1..9 e 0 para a 10ª (pedido literal do usuário)
            tecla = str((i + 1) % 10)
            self.lista.InsertItem(i, f"{tecla} — {nome}")
            self.lista.SetItem(i, 1, self._resumo(c))

    def _salvar_cfg(self) -> None:
        self.cfg["scenes"] = self.cenas
        try:
            from engine.config import salvar
            salvar(self.cfg)
        except Exception:
            pass

    # ---------------------------------------------------------------- ações
    def _nova(self) -> None:
        nome = self.campo_nome.GetValue().strip()
        if not nome:
            self.speech.falar("Informe o nome da cena", interrupt=True)
            return
        if len(self.cenas) >= 10:
            self.speech.falar("Máximo de 10 cenas: as teclas 1 a 9 e 0",
                              interrupt=True)
            return
        cena = self._preset_do_editor()
        cena["nome"] = nome
        self.cenas.append(cena)
        self._salvar_cfg()
        self._recarregar()
        self.campo_nome.SetValue("")
        self.Layout()
        self.speech.falar(f"Cena {len(self.cenas)} criada: {nome}. "
                          f"Tecla {len(self.cenas) % 10}. {self._resumo(cena)}",
                          interrupt=True)

    def _atualizar(self) -> None:
        i = self.lista.GetFocusedItem()
        if not (0 <= i < len(self.cenas)):
            self.speech.falar("Selecione a cena para atualizar", interrupt=True)
            return
        nome = self.campo_nome.GetValue().strip() or self.cenas[i]["nome"]
        cena = self._preset_do_editor()
        cena["id"] = self.cenas[i].get("id", cena["id"])
        cena["nome"] = nome
        self.cenas[i] = cena
        self._salvar_cfg()
        self._recarregar()
        self.texto_status.SetLabel(self._status())
        self.Layout()
        self.speech.falar(f"Cena {i + 1} atualizada: {nome}", interrupt=True)

    def _ativar(self) -> None:
        i = self.lista.GetFocusedItem()
        if not (0 <= i < len(self.cenas)):
            self.speech.falar("Selecione uma cena", interrupt=True)
            return
        self._ativa_idx = i
        cena = self.cenas[i]
        self.texto_status.SetLabel(self._status())
        self.Layout()
        self.speech.falar(f"Cena {i + 1} ativada: {cena['nome']}. "
                          f"{self._resumo(cena)}", interrupt=True)
        cb = getattr(self, "ao_aplicar", None)
        if callable(cb):
            try:
                cb(cena)
            except Exception as e:
                self.speech.falar(f"Erro ao aplicar cena: {e}", interrupt=True)

    def _excluir(self) -> None:
        i = self.lista.GetFocusedItem()
        if not (0 <= i < len(self.cenas)):
            self.speech.falar("Selecione uma cena", interrupt=True)
            return
        nome = self.cenas[i].get("nome", "")
        dlg = wx.MessageDialog(
            self, t("scenes.confirmDelete").replace("{{name}}", nome),
            t("scenes.deleteScene"), wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.cenas.pop(i)
            if self._ativa_idx == i:
                self._ativa_idx = -1
            elif self._ativa_idx > i:
                self._ativa_idx -= 1
            self._salvar_cfg()
            self._recarregar()
            self.texto_status.SetLabel(self._status())
            self.Layout()
            self.speech.falar(f"Cena excluída: {nome}", interrupt=True)
        dlg.Destroy()
