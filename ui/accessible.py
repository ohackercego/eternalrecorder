"""Acessibilidade nativa: classe `wx.Accessible` por controle.

Em wxPython o leitor de tela (NVDA/JAWS) não lê uma árvore DOM interpretada:
ele consulta `IAccessible2`/UIA direto da janela Win32.

Regras aprendidas lendo o WinZapp e errando aqui:

1. **Nome localizado.** Todo controle recebe o nome do dicionário de idioma.
2. **Nada se anuncia por tempo.** Cronômetro e nível entram no nome, lidos ao
   focar. Não há "live region".
3. **`GetState` PRECISA devolver `ACC_STATE_SYSTEM_CHECKED`.** Sem isso o
   leitor não anuncia que o checkbox está marcado — bug relatado.
4. **Controles compostos: `childId > 0` devolve `ACC_NOT_IMPLEMENTED`.** Numa
   lista, sobrescrever o acessível de TODOS os childIds faz o leitor pedir a
   mesma informação a cada linha, entrar em laço e TRAVAR a janela ao descer a
   lista. O WinZapp resolve assim (`AccessibleConversationList`): nome no
   childId 0, nativo para o resto.
"""
from __future__ import annotations

from typing import Callable, Optional

import wx


class ControleAcessivel(wx.Accessible):
    """Acessível genérico: nome e papel vêm de callables.

    `nome_fn` é chamado a cada consulta, não uma vez só — é o que permite o
    botão mudar de "Gravar" para "Parar gravação" e o leitor receber o texto
    novo sem nenhum anúncio espontâneo.
    """

    def __init__(self, controle: wx.Window, nome_fn: Callable[[], str],
                 papel: int = wx.ROLE_SYSTEM_PUSHBUTTON,
                 valor_fn: Optional[Callable[[], str]] = None,
                 estado_fn: Optional[Callable[[], int]] = None) -> None:
        super().__init__()
        self._controle = controle
        self._nome_fn = nome_fn
        self._papel = papel
        self._valor_fn = valor_fn
        self._estado_fn = estado_fn

    def GetName(self, childId):
        try:
            return wx.ACC_OK, self._nome_fn() or ""
        except Exception:
            return wx.ACC_OK, ""

    def GetRole(self, childId):
        return wx.ACC_OK, self._papel

    def GetValue(self, childId):
        if self._valor_fn is None:
            return wx.ACC_NOT_SUPPORTED, ""
        try:
            return wx.ACC_OK, self._valor_fn() or ""
        except Exception:
            return wx.ACC_OK, ""

    def GetState(self, childId):
        """Estado — inclui CHECKED, senão o leitor não anuncia marcado.

        O Windows pergunta o estado para narrar "marcado"/"desmarcado". Antes
        esta função devolvia só foco e disponibilidade, então um checkbox
        marcado soava igual a um desmarcado.
        """
        estado = 0
        try:
            habilitado = self._controle.IsEnabled()
            if habilitado:
                estado |= wx.ACC_STATE_SYSTEM_FOCUSABLE
            else:
                estado |= wx.ACC_STATE_SYSTEM_UNAVAILABLE
            if self._controle.HasFocus():
                estado |= wx.ACC_STATE_SYSTEM_FOCUSED

            if isinstance(self._controle, (wx.CheckBox, wx.RadioButton)):
                try:
                    if self._controle.GetValue():
                        estado |= wx.ACC_STATE_SYSTEM_CHECKED
                except Exception:
                    pass

            if isinstance(self._controle, (wx.ListCtrl, wx.ListBox, wx.Choice)):
                try:
                    if isinstance(self._controle, wx.ListCtrl):
                        if self._controle.GetSelectedItemCount() > 0:
                            estado |= wx.ACC_STATE_SYSTEM_SELECTED
                    elif self._controle.GetSelection() >= 0:
                        estado |= wx.ACC_STATE_SYSTEM_SELECTED
                except Exception:
                    pass

            if self._estado_fn is not None:
                try:
                    estado |= int(self._estado_fn() or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return wx.ACC_OK, estado


class BotaoAcessivel(ControleAcessivel):
    """Botão com nome dinâmico (muda com o estado da gravação)."""

    def __init__(self, controle, nome_fn: Callable[[], str]) -> None:
        super().__init__(controle, nome_fn, wx.ROLE_SYSTEM_PUSHBUTTON)


class CaixaAcessivel(ControleAcessivel):
    """Checkbox que anuncia marcado/desmarcado.

    Além do `GetState` (que o MSAA consulta), o estado vai no NOME em texto:
    alguns leitores sobre wxWidgets não consultam GetState e só leem o nome.
    """

    def __init__(self, controle, nome_fn: Callable[[], str],
                 incluir_estado_no_nome: bool = True) -> None:
        self._incluir = incluir_estado_no_nome
        super().__init__(controle, lambda: self._nome_com_estado(nome_fn),
                         wx.ROLE_SYSTEM_CHECKBUTTON)

    def _nome_com_estado(self, nome_fn) -> str:
        base = nome_fn() or ""
        if not self._incluir:
            return base
        try:
            marcado = self._controle.GetValue()
        except Exception:
            return base
        return f"{base}, {'marcado' if marcado else 'desmarcado'}"


class CampoAcessivel(ControleAcessivel):
    """Campo de texto/valor: nome fixo, valor lido do controle.

    Campo READ-ONLY (o caso da pasta de gravação): o leitor precisa SABER
    que é somente leitura, senão o usuário tenta editar, não consegue, e
    conclui que o campo está quebrado. O estado vai no NOME — "somente
    leitura" é lido junto — porque regioes vivas e estados soltos não são
    anunciados com consistência por todos os leitores.
    """

    def __init__(self, controle, nome: str,
                 valor_fn: Optional[Callable[[], str]] = None) -> None:
        somente = bool(getattr(controle, "IsEditable", None)
                       and not controle.IsEditable())

        def _nome():
            if somente:
                return f"{nome}, somente leitura"
            return nome

        super().__init__(
            controle,
            _nome,
            wx.ROLE_SYSTEM_TEXT,
            valor_fn or (lambda: controle.GetValue()
                         if hasattr(controle, "GetValue") else ""),
        )


class EscolhaAcessivel(ControleAcessivel):
    """Combo/listbox: nome, valor = item selecionado. Filhos ficam nativos."""

    def __init__(self, controle, nome: str) -> None:
        super().__init__(
            controle,
            (lambda: nome),
            wx.ROLE_SYSTEM_COMBOBOX,
            lambda: controle.GetStringSelection()
            if hasattr(controle, "GetStringSelection") else "",
        )


class ListaAcessivel(wx.Accessible):
    """Lista: nome no childId 0, resto deixa o nativo responder.

    Esta é a correção do travamento. Sobrescrever `GetName`/`GetRole` para
    TODOS os childIds faz o leitor pedir a mesma informação a cada linha e
    entrar em laço — a janela trava ao descer a lista. Devolver
    `ACC_NOT_IMPLEMENTED` para childId > 0 faz o MSAA usar o handler nativo,
    que expõe as linhas corretamente.
    """

    def __init__(self, controle: wx.Window, nome_fn: Callable[[], str]) -> None:
        super().__init__()
        self._controle = controle
        self._nome_fn = nome_fn

    def GetName(self, childId):
        if childId == 0:
            try:
                return wx.ACC_OK, self._nome_fn() or ""
            except Exception:
                return wx.ACC_OK, ""
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetRole(self, childId):
        if childId == 0:
            return wx.ACC_OK, wx.ROLE_SYSTEM_LIST
        return wx.ACC_NOT_IMPLEMENTED, 0

    def GetValue(self, childId):
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetState(self, childId):
        if childId != 0:
            return wx.ACC_NOT_IMPLEMENTED, 0
        estado = 0
        try:
            if self._controle.IsEnabled():
                estado |= wx.ACC_STATE_SYSTEM_FOCUSABLE
            if self._controle.HasFocus():
                estado |= wx.ACC_STATE_SYSTEM_FOCUSED
        except Exception:
            pass
        return wx.ACC_OK, estado


class StatusAcessivel(ControleAcessivel):
    """Rótulo de status: papel de texto, lido sob demanda (sem live region)."""

    def __init__(self, controle, nome_fn: Callable[[], str]) -> None:
        super().__init__(controle, nome_fn, wx.ROLE_SYSTEM_STATICTEXT)


def aplicar(controle: wx.Window, acessivel: wx.Accessible) -> wx.Accessible:
    """Liga o acessível ao controle e GUARDA a referência.

    Objeto sem referência pode ser coletado e o controle volta a ser anônimo.
    """
    try:
        controle._acessivel = acessivel
    except Exception:
        pass
    controle.SetAccessible(acessivel)
    return acessivel


def botao(pai: wx.Window, rotulo_fn: Callable[[], str], ao_clicar,
          nome_fn: Optional[Callable[[], str]] = None) -> wx.Button:
    """Cria um botão já acessível."""
    btn = wx.Button(pai, label=rotulo_fn())
    btn.Bind(wx.EVT_BUTTON, ao_clicar)
    aplicar(btn, BotaoAcessivel(btn, nome_fn or rotulo_fn))
    return btn


def caixa(pai: wx.Window, rotulo_fn: Callable[[], str],
          valor: bool = False) -> wx.CheckBox:
    """Cria um checkbox que anuncia marcado/desmarcado."""
    chk = wx.CheckBox(pai, label=rotulo_fn())
    chk.SetValue(valor)
    aplicar(chk, CaixaAcessivel(chk, rotulo_fn))
    return chk


def lista(pai: wx.Window, nome_fn: Callable[[], str],
          estilo: int = wx.LC_REPORT | wx.LC_SINGLE_SEL,
          tamanho=(-1, 160)) -> wx.ListCtrl:
    """Cria uma lista com acessível que NÃO sobrescreve as linhas."""
    lc = wx.ListCtrl(pai, style=estilo, size=tamanho)
    aplicar(lc, ListaAcessivel(lc, nome_fn))
    return lc


def rotulo(pai: wx.Window, texto_fn, estilo: int = 0) -> wx.StaticText:
    """Rótulo de texto com nome acessível dinâmico."""
    txt = wx.StaticText(pai, label=texto_fn() if callable(texto_fn) else texto_fn,
                        style=estilo)
    nome_fn = texto_fn if callable(texto_fn) else (lambda: str(texto_fn))
    aplicar(txt, StatusAcessivel(txt, nome_fn))
    return txt
