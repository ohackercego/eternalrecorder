"""Eternal Recorder — janela principal com as 4 abas.

Espelha a estrutura do build Electron: Gravação, Cenas, Configurações,
Transmissão. Cada aba é um painel wxPython com acessibilidade nativa.

Acessibilidade das abas: um `wx.Notebook` já expõe papel de tabulação para o
leitor, então não é preciso `wx.Accessible` por aba — o controle nativo já
responde `ROLE_SYSTEM_PAGETAB`. O que importa é o nome de cada página, que vem
do dicionário de idioma.
"""
from __future__ import annotations

import sys
from pathlib import Path

import wx
import wx.adv

from engine.logs import logger
_log = logger("ui.app")

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.i18n import t
from ui.speech import Speech
from engine import config as config_engine


class Janela(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title=t("app.name"), size=(920, 740))
        self.speech = Speech()
        self.cfg = config_engine.carregar()

        # idioma SALVO tem prioridade sobre o do sistema: o usuário escolheu
        # na aba de configurações e espera que continue valendo no próximo boot
        try:
            from ui import i18n as modulo_i18n
            salvo = str(self.cfg.get("idioma") or "").strip()
            if salvo and salvo != "auto":
                modulo_i18n.carregar(salvo)
        except Exception:
            pass

        # motor: carrega uma vez; se falhar, a UI abre e explica
        self.motor = None
        try:
            from engine.motor_obs import Motor
            self.motor = Motor()
        except Exception as e:
            print(f"[ui] motor não carregou: {e}", file=sys.stderr)

        self._montar_abas()
        self._montar_atalhos()
        self._montar_bandeja()
        # liga a cena ao painel de gravação — era o bug: o callback nunca era
        # registrado, então "ativar cena" só falava e não aplicava nada
        self.p_cenas.ao_aplicar = self.p_gravacao.aplicar_cena
        self.CreateStatusBar()
        self.SetStatusText(t("app.statusHint"))
        self._atualizar_titulo()
        self.Centre()

    # ------------------------------------------------------------------ abas
    def _montar_abas(self) -> None:
        from ui.painel_gravacao import PainelGravacao
        from ui.painel_cenas import PainelCenas
        from ui.painel_config import PainelConfiguracoes
        from ui.painel_transmissao import PainelTransmissao

        self.abas = wx.Notebook(self)

        self.p_gravacao = PainelGravacao(self.abas, self.speech, self.motor,
                                         self.cfg)
        self.abas.AddPage(self.p_gravacao, t("tabs.recorder"))

        self.p_cenas = PainelCenas(self.abas, self.speech, self.cfg, self.motor)
        self.abas.AddPage(self.p_cenas, t("tabs.scenes"))

        self.p_config = PainelConfiguracoes(self.abas, self.speech, self.cfg)
        self.p_config.ao_mudar_idioma = self._ao_mudar_idioma
        self.p_config.ao_mudar_atalhos = self._recarregar_atalhos
        self.abas.AddPage(self.p_config, t("tabs.settings"))

        self.p_transmissao = PainelTransmissao(self.abas, self.speech, self.cfg)
        self.p_transmissao.atualizar_cenas(
            getattr(self.p_cenas, "cenas", []))
        self.p_transmissao.ligar_motor(
            self.motor,
            lambda: self.p_gravacao._sessao,
            cenas_provider=lambda: getattr(self.p_gravacao, "cena_aplicada",
                                           None))
        self.abas.AddPage(self.p_transmissao, t("tabs.transmission"))

        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(self.abas, 1, wx.EXPAND)
        self.SetSizer(s)

        self.abas.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._ao_trocar_aba)

    def _ao_trocar_aba(self, ev) -> None:
        ev.Skip()
        i = ev.GetSelection()
        nome = self.abas.GetPageText(i)
        self.speech.falar(nome)
        # foco no primeiro botão da aba, senão o leitor fica sem referência
        pagina = self.abas.GetPage(i)
        for filho in pagina.GetChildren():
            if isinstance(filho, wx.Button):
                filho.SetFocus()
                break

    def _ao_mudar_idioma(self, codigo: str) -> None:
        """Idioma mudou: salva e RECONSTRÓI a janela na hora.

        Antes só salvava e pedia reabertura — o usuário trocava na caixa e nada
        mudava na tela (relatado). Reconstruir é o único jeito de os rótulos já
        criados refletirem o idioma novo, porque `t()` foi chamado na criação.

        Não recria com gravação em andamento: isso perderia a sessão.
        """
        try:
            self.cfg["idioma"] = codigo
            config_engine.salvar(self.cfg)
        except Exception:
            pass

        if getattr(self.p_gravacao, "gravando", False):
            self.SetStatusText("Idioma salvo. Pare a gravação e troque de novo "
                               "para aplicar.")
            return

        from ui import i18n as modulo_i18n
        modulo_i18n.carregar(codigo)
        self.speech.falar(t("config.idiomaAplicadoFala"))

        # reconstrói a janela: destrói o conteúdo e remonta no idioma novo
        try:
            self.Freeze()
            self.SetSizer(None)
            for filho in list(self.GetChildren()):
                if not isinstance(filho, wx.StatusBar):
                    filho.Destroy()
            self._montar_abas()
            self._montar_atalhos()
            self.Layout()
            self.Thaw()
            self.p_gravacao.btn_principal.SetFocus()
        except Exception as e:
            try:
                self.Thaw()
            except Exception:
                pass
            self.SetStatusText(f"Erro ao aplicar idioma: {e}")

    def _atualizar_titulo(self) -> None:
        if self.motor and self.motor.disponivel:
            n_mon = len(self.motor.monitores())
            n_jan = len(self.motor.janelas())
            self.SetTitle(f'{t("app.name")} — {n_mon} monitor(es), '
                          f'{n_jan} janela(s)')
        else:
            self.SetTitle(f'{t("app.name")} — motor indisponível')

    # ------------------------------------------------------------------ atalhos
    def _montar_atalhos(self) -> None:
        """Atalhos: acelerador LOCAL (janela focada) + GLOBAL (fora do app).

        O relato "atalhos não funcionam fora do app" tinha causa estrutural:
        gravar/parar/pausar/mudo estavam **apenas** no `AcceleratorTable` do
        wx, que só dispara com a janela focada. Como quem grava está sempre em
        outro programa, esses atalhos nunca funcionaram fora do app — só as
        cenas (Ctrl+1..0), o F10 e o Ctrl+Shift+H, que já usavam
        `RegisterHotKey`.

        Aqui ficam os dois caminhos:
          - LOCAL (AcceleratorTable): teclas 1..0 NUAS e também as combinações,
            para funcionar quando a janela tem foco (inclusive com o wx
            segurando a tecla antes do sistema);
          - GLOBAL (`ui.hotkeys`): TODAS as ações, via `RegisterHotKey`.
        """
        p = self.p_gravacao
        self._acoes_atalho = {
            "start": lambda: self._agir(p.gravar),
            "stop": lambda: self._agir(p.parar),
            "pause": lambda: self._agir(p._alternar_pausa),
            "mute": lambda: self._agir(p._alternar_mudo),
            "toggleAudio": lambda: p.chk_sistema.SetValue(
                not p.chk_sistema.GetValue()),
            "toggleWindow": lambda: self.abas.SetSelection(
                0 if self.abas.GetSelection() != 0 else 1),
            "menu": self._mostrar_menu_bandeja,
            "reabrir": self.reabrir_da_bandeja,
        }

        # ── tabela de aceleradores da JANELA ──
        # só as teclas de cena nuas: acelerador local não serve para ação de
        # gravação (o usuário estaria em outro app). Os ids das ações vêm do
        # próprio módulo de hotkeys para não haver duas numerações.
        from ui.hotkeys import ACOES, _ID_CENA_BASE
        self._ids_acao = {k: v for k, v in ACOES.items()}
        self._acel = []
        self._ids_cena = []
        for i in range(10):
            vk = 0x30 if i == 9 else (0x31 + i)
            idc = _ID_CENA_BASE + i
            self._ids_cena.append(idc)
            self._acel.append((wx.ACCEL_NORMAL, vk, idc))
            self.Bind(wx.EVT_MENU,
                      lambda e, idx=i: self._ativar_cena_por_tecla(idx),
                      id=idc)
        # as combinações globais também funcionam localmente: se o wx processar
        # a tecla antes do sistema, o EVT_MENU cai no mesmo handler da ação
        from ui.hotkeys import parse_atalho
        for nome, funcao in self._acoes_atalho.items():
            texto = (self.cfg.get("shortcuts") or {}).get(nome, "")
            analisado = parse_atalho(texto) if texto else None
            if not analisado:
                continue
            mods, vk = analisado
            flags = 0
            if mods & 0x0002:
                flags |= wx.ACCEL_CTRL
            if mods & 0x0004:
                flags |= wx.ACCEL_SHIFT
            if mods & 0x0001:
                flags |= wx.ACCEL_ALT
            hid = self._ids_acao[nome]
            self._acel.append((flags, vk, hid))
            self.Bind(wx.EVT_MENU, lambda e, f=funcao: f(), id=hid)
        self.SetAcceleratorTable(wx.AcceleratorTable(self._acel))

        self._montar_hotkeys_globais()
        self.Bind(wx.EVT_WINDOW_DESTROY, self._ao_destruir, self)

    # ─────────────────────────────────────── atalhos GLOBAIS
    def _montar_hotkeys_globais(self) -> None:
        """Registra TODAS as ações via RegisterHotKey (funciona fora do app)."""
        from ui.hotkeys import GerenciadorAtalhos
        try:
            self._hot = GerenciadorAtalhos(self)
        except Exception as e:
            _log.error("hotkeys: gerenciador não criou (%s: %s)",
                       type(e).__name__, e)
            self._hot = None
            return
        atalhos = dict(self.cfg.get("shortcuts") or {})
        # F10 abre o menu da bandeja; combinação padrão se faltar no config
        atalhos.setdefault("menu", "F10")
        self._hot.registrar_acoes(atalhos, self._acoes_atalho)
        self._hot.registrar_cenas(len(getattr(self.p_cenas, "cenas", [])) or 10,
                                  self._ativar_cena_por_tecla)
        _log.info("hotkeys globais: %s", self._hot.resumo())
        # colisão = atalho que o usuário vai jurar que está quebrado; avisa
        if self._hot.falhas:
            wx.CallAfter(self.speech.falar,
                         "Atenção: " + self._hot.resumo(), True)

    def _agir(self, acao) -> None:
        """Leva o usuário à aba de gravação antes de agir por atalho.

        É o mesmo comportamento do build Electron: o atalho funciona de
        qualquer lugar, mas a UI mostra a aba onde a ação aconteceu.
        """
        try:
            if self.abas.GetSelection() != 0:
                self.abas.SetSelection(0)
        except Exception:
            pass
        acao()

    def _recarregar_atalhos(self, atalhos: dict) -> None:
        """Aplica combinações novas sem reiniciar o app."""
        if getattr(self, "_hot", None) is None:
            return
        self._hot.recarregar(
            dict(atalhos or {}), self._acoes_atalho,
            total_cenas=len(getattr(self.p_cenas, "cenas", [])) or 10,
            ao_cena=self._ativar_cena_por_tecla)
        self.speech.falar(self._hot.resumo(), interrupt=True)

    def _ativar_cena_por_tecla(self, indice: int) -> None:
        _log.info("hotkey de cena %d (cadastradas: %d)",
                  indice + 1, len(getattr(self.p_cenas, "cenas", [])))
        cenas = getattr(self.p_cenas, "cenas", [])
        if indice >= len(cenas):
            self.speech.falar(
                t("cenaFalas.naoExiste").replace("{n}", str(indice + 1))
                  .replace("{total}", str(len(cenas))), interrupt=True)
            return
        # foca a linha na aba Cenas e ativa (mesmo caminho do botão)
        try:
            self.p_cenas.lista.Focus(indice)
            self.p_cenas.lista.Select(indice)
        except Exception:
            pass
        self.p_cenas._ativa_idx = indice
        cena = cenas[indice]
        self.p_cenas.texto_status.SetLabel(self.p_cenas._status())
        self.p_cenas.Layout()
        self.speech.falar(
            t("cenaFalas.aplicadaVivo")
              .replace("{n}", str(indice + 1))
              .replace("{nome}", str(cena.get("nome", "")))
              .replace("{resumo}", self.p_cenas._resumo(cena)),
            interrupt=True)
        cb = self.p_cenas.ao_aplicar
        if callable(cb):
            try:
                cb(cena)
            except Exception as e:
                self.speech.falar(
                    t("cenas.erroAplicar").replace("{erro}", str(e)),
                    interrupt=True)
        # o seletor da transmissão acompanha a cena ativa
        try:
            self.p_transmissao.atualizar_cenas(cenas, indice)
        except Exception:
            pass

    def _ao_destruir(self, ev) -> None:
        """Libera as hotkeys registradas — senão ficam presas no Windows."""
        self._desregistrar_hotkeys()
        ev.Skip()

    def _desregistrar_hotkeys(self) -> None:
        """Desregistra tudo. Sem isso as teclas continuam capturadas com o
        processo vivo na bandeja — bug relatado."""
        if getattr(self, "_hot", None) is not None:
            self._hot.encerrar()

    # ------------------------------------------------------------------ bandeja
    _ID_BANDEJA_RESTAURAR = wx.NewIdRef()
    _ID_BANDEJA_SAIR = wx.NewIdRef()
    _ID_BANDEJA_GITHUB = wx.NewIdRef()

    def _montar_bandeja(self) -> None:
        """Ícone na bandeja + fechar minimiza em vez de sair.

        Pedido: "o comportamento de ir para a bandeja não funciona; quando eu
        fecho com alt f4 ou sair, ele simplesmente não vai pra bandeja e fecha
        completamente". Causa: não havia TaskBarIcon nem EVT_CLOSE — o wx
        destrói a janela no Alt-F4 por padrão. Aqui: EVT_CLOSE é interceptado;
        se a config `fechar_para_bandeja` estiver ligada (padrão: sim), a
        janela esconde e o ícone fica na bandeja. Sair de verdade é pelo menu
        da bandeja ou pela config.
        """
        self._bandeja = Bandeja(self)
        self.Bind(wx.EVT_CLOSE, self._ao_fechar)

        # ── ALT abre o menu: wx.MenuBar ──
        # No Windows, Alt ativa a barra de menus da janela focada. Um
        # MenuBar com o menu "Sistema" (Reabrir/GitHub/Sair) é o caminho
        # nativo do wx para o Alt funcionar — sem sequestrar a tecla.
        menu_sistema = wx.Menu()
        # SEM "Reabrir" aqui: o reabrir fica na bandeja (pedido do usuário —
        # reabrir dentro da janela não faz sentido, a janela já está aberta)
        menu_sistema.Append(self._ID_BANDEJA_GITHUB,
                            t("tray.github") + "\tALT+G")
        menu_sistema.Append(self._ID_BANDEJA_SAIR, t("tray.quit"))
        bar = wx.MenuBar()
        bar.Append(menu_sistema, "&Sistema\tALT+M")   # Alt+M abre o menu
        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, lambda e: self.reabrir_da_bandeja(),
                  id=self._ID_BANDEJA_RESTAURAR)
        self.Bind(wx.EVT_MENU, self._abrir_github,
                  id=self._ID_BANDEJA_GITHUB)
        self.Bind(wx.EVT_MENU, self._sair_de_verdade,
                  id=self._ID_BANDEJA_SAIR)

    def _abrir_github(self, ev=None) -> None:
        import webbrowser
        _log.info("abrindo o projeto no GitHub (menu da janela)")
        try:
            webbrowser.open(t("app.githubUrl"))
            self.speech.falar(t("tray.githubOpened"), interrupt=True)
        except Exception as e:
            _log.error("falha ao abrir o GitHub: %s", e)

    def _sair_de_verdade(self, ev=None) -> None:
        self.cfg["closeBehavior"] = "exit"
        try:
            from engine import config as config_engine
            config_engine.salvar(self.cfg)
        except Exception:
            pass
        self._desregistrar_hotkeys()
        if self._bandeja:
            self._bandeja.remover()
            self._bandeja = None
        self.Close(force=True)

    def _ao_fechar(self, ev) -> None:
        """Alt-F4 / X: esconder para a bandeja (config) ou sair de verdade.

        O controle é o combo "Comportamento ao fechar" da aba Configurações
        (closeBehavior: exit | tray). Não há checkbox além dele.
        """
        if self.cfg.get("closeBehavior", "tray") != "exit" and self._bandeja:
            # gravação em andamento NÃO esconde silenciosamente: avisaria mal
            if getattr(self.p_gravacao, "gravando", False):
                dlg = wx.MessageDialog(
                    self, t("bandeja.gravacaoAtiva"),
                    t("bandeja.tituloGravando"),
                    wx.YES_NO | wx.ICON_QUESTION)
                resp = dlg.ShowModal()
                dlg.Destroy()
                if resp != wx.ID_YES:
                    return      # não fecha: usuário decide
            self.Hide()
            _log.info("janela escondida para a bandeja (ícone instalado=%s)",
                      self._bandeja.IsIconInstalled() if self._bandeja
                      else False)
            self._bandeja.aviso(t("bandeja.avisoBandeja"))
            self.speech.falar(t("bandeja.escondeu"), interrupt=True)
        else:
            # sair de verdade: destrói a bandeja também
            try:
                if self._bandeja:
                    self._bandeja.remover()
                    self._bandeja = None
            except Exception:
                pass
            ev.Skip()

    def _mostrar_menu_bandeja(self) -> None:
        """Abre o menu da bandeja (Reabrir/GitHub/Sair) na posição atual."""
        _log.info("mostrando o menu da bandeja (F10)")
        try:
            if self._bandeja:
                pos = wx.GetMousePosition()
                # TaskBarIcon não tem PopupMenu público: recrio o menu e
                # mostro na tela — mesmo efeito do clique direito
                menu = self._bandeja.CreatePopupMenu()
                if menu:
                    self.PopupMenu(menu)
                menu.Destroy()
                self.speech.falar(t("bandeja.menuAberto"), interrupt=True)
        except Exception as e:
            _log.error("menu da bandeja falhou: %s", e)

    def reabrir_da_bandeja(self) -> None:
        _log.info("reabrir_da_bandeja (Ctrl+Shift+H ou clique no ícone)")
        self.Show()
        self.Iconize(False)
        self.Raise()
        self.SetFocus()
        self.p_gravacao.btn_principal.SetFocus()


class Bandeja(wx.adv.TaskBarIcon):
    """Ícone da bandeja do sistema com menu: reabrir / sair."""

    def __init__(self, janela: "Janela") -> None:
        super().__init__()
        self.janela = janela
        # ── ícone OBRIGATÓRIO ──
        # BUG: usei wx.ART_COMPONENT, que NÃO EXISTE no wx Phoenix — o
        # AttributeError era engolido pelo except, SetIcon nunca rodava e o
        # ícone nunca aparecia. Resultado: o app escondia a janela sem ícone
        # nenhum = INVISÍVEL (o usuário não tinha como reabrir, e o Ctrl+Shift+H
        # parecia não fazer nada porque o app até respondia, mas não havia
        # ícone para clicar). ART_INFORMATION existe e é verificado.
        icone = wx.ArtProvider.GetIcon(wx.ART_INFORMATION,
                                       wx.ART_OTHER, (32, 32))
        instalado = False
        if icone.IsOk():
            instalado = self.SetIcon(icone, t("app.name"))
        _log = logger("ui.bandeja")
        _log.info("ícone da bandeja: instalado=%s", instalado)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self._reabrir)
        self.Bind(wx.EVT_MENU, self._reabrir, id=janela._ID_BANDEJA_RESTAURAR)
        self.Bind(wx.EVT_MENU, self._github, id=janela._ID_BANDEJA_GITHUB)
        self.Bind(wx.EVT_MENU, self._sair, id=janela._ID_BANDEJA_SAIR)

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(self.janela._ID_BANDEJA_RESTAURAR,
                    t("tray.reopen"))
        menu.AppendSeparator()
        menu.Append(self.janela._ID_BANDEJA_GITHUB, t("tray.github"))
        menu.Append(self.janela._ID_BANDEJA_SAIR, t("tray.quit"))
        return menu

    def _github(self, ev=None) -> None:
        """Abre o projeto no GitHub (ohackercego/eternalrecorder)."""
        import webbrowser
        _log.info("abrindo o projeto no GitHub")
        try:
            webbrowser.open(t("app.githubUrl"))
            self.janela.speech.falar(t("tray.githubOpened"), interrupt=True)
        except Exception as e:
            _log.error("falha ao abrir o GitHub: %s", e)

    def _reabrir(self, ev=None) -> None:
        self.janela.reabrir_da_bandeja()

    def _sair(self, ev=None) -> None:
        # saída REAL: limpa a config para o próximo fechar sair também
        self.janela.cfg["fechar_para_bandeja"] = False
        try:
            from engine import config as config_engine
            config_engine.salvar(self.janela.cfg)
        except Exception:
            pass
        # DESREGISTRA as hotkeys ANTES de fechar — com o processo vivo na
        # bandeja, as teclas ficavam capturadas (bug relatado)
        try:
            self.janela._desregistrar_hotkeys()
        except Exception:
            pass
        self.remover()
        self.janela.Close(force=True)

    def aviso(self, texto: str) -> None:
        try:
            self.notify(texto, t("app.name"))
        except Exception:
            pass

    def remover(self) -> None:
        try:
            self.RemoveIcon()
            self.Destroy()
        except Exception:
            pass


def main() -> int:
    app = wx.App(False)
    janela = Janela()
    janela.Show()
    janela.p_gravacao.btn_principal.SetFocus()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
