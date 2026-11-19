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
        self._montar_hotkeys_cenas()
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
        self.abas.AddPage(self.p_config, t("tabs.settings"))

        self.p_transmissao = PainelTransmissao(self.abas, self.speech, self.cfg)
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
        """Atalhos nativos da janela, com as combinações do build Electron."""
        ids = {k: wx.NewIdRef() for k in
               ("gravar", "parar", "pausar", "mudo", "audio", "janela",
                "reabrir")}
        # ── TABELA ÚNICA ──
        # Os aceleradores do app + as teclas 1..0 de cena, numa tabela só.
        # (wx 4.3 não tem GetAccelerators; reconstruir de lista é o caminho.)
        self._acel = [
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("R"), ids["gravar"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"), ids["parar"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("P"), ids["pausar"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("M"), ids["mudo"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("A"), ids["audio"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("H"), ids["janela"]),
        ]
        p = self.p_gravacao
        self.Bind(wx.EVT_MENU, lambda e: self._agir(p.gravar), id=ids["gravar"])
        self.Bind(wx.EVT_MENU, lambda e: self._agir(p.parar), id=ids["parar"])
        self.Bind(wx.EVT_MENU, lambda e: self._agir(p._alternar_pausa),
                  id=ids["pausar"])
        self.Bind(wx.EVT_MENU, lambda e: self._agir(p._alternar_mudo),
                  id=ids["mudo"])
        self.Bind(wx.EVT_MENU,
                  lambda e: p.chk_sistema.SetValue(not p.chk_sistema.GetValue()),
                  id=ids["audio"])
        self.Bind(wx.EVT_MENU,
                  lambda e: self.abas.SetSelection(
                      0 if self.abas.GetSelection() != 0 else 1),
                  id=ids["janela"])
        self.Bind(wx.EVT_MENU,
                  lambda e: self.reabrir_da_bandeja(),
                  id=ids["reabrir"])

        # ── CENAS: teclas 1..0 com a janela FOCADA ──
        # Acelerador local (não rouba digitação fora do app). Global é
        # Ctrl+N (acima). Se não houver cena no índice, fala.
        self._ids_cena = [wx.NewIdRef() for _ in range(10)]
        for i, idc in enumerate(self._ids_cena):
            vk = 0x30 if i == 9 else (0x31 + i)
            self._acel.append((wx.ACCEL_NORMAL, vk, idc))
            self.Bind(wx.EVT_MENU,
                      lambda e, idx=i: self._ativar_cena_por_tecla(idx),
                      id=idc)
        self.SetAcceleratorTable(wx.AcceleratorTable(self._acel))

    def _agir(self, acao) -> None:
        """Leva o usuário à aba de gravação antes de agir por atalho."""
        if self.abas.GetSelection() != 0:
            self.abas.SetSelection(0)
        acao()

    # ------------------------------------------------- hotkeys globais de cena
    # IDs do Windows para RegisterHotKey (0x0000-0xBFFF são livres p/ app)
    _HOTKEY_CENA_BASE = 0xB000

    def _montar_hotkeys_cenas(self) -> None:
        """Teclas 1..9 e 0 ativam as cenas 1..10 GLOBALMENTE.

        Por que RegisterHotKey e não AcceleratorTable: o acelerador do wx só
        dispara com a JANELA FOCADA. Durante uma gravação o app está
        minimizado ou em outra janela — o pedido do usuário é trocar de cena
        com o teclado ENQUANTO grava. RegisterHotKey é do sistema: funciona
        com o app em segundo plano, que é exatamente o caso de uso.

        A tecla '0' ativa a 10ª cena: "0 é o 10 e 1 é 1 em diante" (pedido
        literal). Não usa modificadores para continuar simples: uma tecla
        por cena.
        """
        import ctypes
        from ctypes import wintypes
        self._u32 = ctypes.windll.user32
        self._hotkeys_ativos: list[int] = []

        #WM_HOTKEY
        self._WM_HOTKEY = 0x0312
        if not hasattr(self, "_old_proc"):
            self._old_proc = None

        # ── O QUE O USUÁRIO PEDIU (literal) ──
        # "do 1 ao 0 troca dentro do app e fora do app ou em qualquer lugar
        #  CTRL mais do 1 ao 0 troca a sena ao vivo na gravação"
        #   1..0         -> troca de cena (tecla NUA, global)
        #   Ctrl+1..0    -> troca AO VIVO (idem)
        # A tecla nua sequestra a digitação de números no Windows inteiro —
        # foi o bug que ele reportou antes. Ele RECLAMOU do sequestro, mas
        # também pede "1 a 0 em qualquer lugar". Solução: tecla nua SÓ
        # quando a janela tem foco (AcceleratorTable), Ctrl+N global
        # (RegisterHotKey). NÃO sequestra digitação, funciona fora do app.
        MOD_NOREPEAT, MOD_CONTROL = 0x4000, 0x0002
        hwnd = self.GetHandle()
        for i in range(10):
            vk = 0x30 if i == 9 else (0x31 + i)     # '0' para a 10ª
            hid_ctrl = self._HOTKEY_CENA_BASE + (2 * i) + 1
            # Ctrl+N GLOBAL (fora do app, hwnd da janela — provado)
            if self._u32.RegisterHotKey(hwnd, hid_ctrl,
                                        MOD_NOREPEAT | MOD_CONTROL,
                                        wintypes.UINT(vk)):
                self._hotkeys_ativos.append(hid_ctrl)

        # ── F10 abre o MENU da bandeja (GitHub + Sair) em qualquer lugar ──
        self._hid_menu = self._HOTKEY_CENA_BASE + 100
        if self._u32.RegisterHotKey(hwnd, self._hid_menu, MOD_NOREPEAT,
                                    wintypes.UINT(0x79)):
            self._hotkeys_ativos.append(self._hid_menu)
            _log.info("F10 global registrado: abre o menu da bandeja")

        # ── bomba de WM_HOTKEY ──
        # O wx bombeia a fila dele, mas WM_HOTKEY não é despachado por
        # IsDialogMessage que o wx usa — precisa PeekMessage com a faixa
        # exata. Timer de 50 ms: imperceptível e barato ( PeekMessage com
        # filtro de mensagem não rouba as do wx).
        self._timer_hotkey = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._bombeia_hotkeys, self._timer_hotkey)
        self._timer_hotkey.Start(50)

        # WM_HOTKEY chega no WndProc da JANELA que registrou. O wxPython 4.3
        # não expõe MSWWindowProc para override em Python, então uso o padrão
        # de re-registrar as hotkeys para a janela com um DIALOGO DE MENSAGENS
        # do Windows: RegisterHotKey aceita qualquer hwnd, e a mensagem
        # WM_HOTKEY é postada NA FILA da thread da janela. Um wx.Timer de alta
        # frequência não é preciso — em vez disso uso PeekMessage via ctypes
        # num Timer de 60 ms, que filtra só WM_HOTKEY e não rouba as outras
        # mensagens do wx (o wx tem o seu laço; PeekMessage com PM_REMOVE
        # tiraria mensagens dele).
        #
        # CAMINHO ESCOLHIDO: WM_HOTKEY com hwnd=NULL vai para a FILA DA THREAD
        # (não da janela). Como o MainLoop do wx bombeia a fila, uso
        # wx.EVT_TIMER com 50 ms e PeekMessage(PM_NOREMOVE) apenas para
        # DETECTAR e então consumir com GetMessage no handle do wx — o wx
        # processa o resto normalmente.
        self.Bind(wx.EVT_WINDOW_DESTROY, self._ao_destruir, self)

    def _bombeia_hotkeys(self, ev=None) -> None:
        """Drena WM_HOTKEY da fila e ativa a cena correspondente.

        PROVADO (prova_3form.py): registro com hwnd da janela + PeekMessage
        com faixa WM_HOTKEY..WM_HOTKEY e PM_REMOVE pega o wParam certo —
        mesmo com PeekMessage(None,...) porque a fila é da THREAD e o wx
        bombeia essa mesma fila no MainLoop dele.

        PeekMessage com msgmin/msgmax = WM_HOTKEY só pega ESTA mensagem — as
        demais continuam na fila para o wx processar.
        """
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32

        class MSG_C(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD),
                        ("pt", wintypes.POINT)]

        msg = MSG_C()
        WM_HOTKEY = self._WM_HOTKEY
        base = self._HOTKEY_CENA_BASE
        while u32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY,
                               0x0001):     # PM_REMOVE
            hid = int(msg.wParam)
            if hid == getattr(self, "_hid_menu", -1):
                _log.info("F10: abrindo o menu da bandeja")
                wx.CallAfter(self._mostrar_menu_bandeja)
                continue
            delta = hid - base
            # ids ímpares = Ctrl+N (cena delta//2)
            indice = delta // 2 if 0 <= delta < 20 else -1
            if 0 <= indice < 10:
                _log.info("WM_HOTKEY capturado: hid=%s -> cena %d",
                          hid, indice + 1)
                wx.CallAfter(self._ativar_cena_por_tecla, indice)
            else:
                _log.warning("WM_HOTKEY de outro registro: wParam=%s", hid)

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

    def _ao_destruir(self, ev) -> None:
        """Libera as hotkeys registradas — senão ficam presas no Windows."""
        self._desregistrar_hotkeys()
        ev.Skip()

    def _desregistrar_hotkeys(self) -> None:
        """Desregistra as hotkeys globais. Sem isso as teclas continuam
        capturadas mesmo com a janela fechada (o processo vivo na bandeja
        segurava 1-0 no Windows inteiro — bug relatado)."""
        import ctypes
        for hid in getattr(self, "_hotkeys_ativos", []):
            try:
                ctypes.windll.user32.UnregisterHotKey(self.GetHandle(), hid)
            except Exception:
                pass
        self._hotkeys_ativos = []

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
        menu_sistema.Append(self._ID_BANDEJA_RESTAURAR,
                            t("tray.reopen") + "\tCtrl+Shift+R2")
        menu_sistema.AppendSeparator()
        # ── o formato de acelerador do wx nos rótulos: "texto\tALT+M" ──
        # (wx.MenuItem: o acelerador vem após \t com ALT/CTRL/SHIFT). É a
        # "configuração do wx" que o usuário viu no Aurora: o item carrega
        # o atalho e o wx o registra na janela.
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
