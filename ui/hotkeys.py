"""Atalhos globais do Eternal Recorder (Windows).

POR QUE ESTE MÓDULO EXISTE
==========================
O bug relatado: "atalhos não funcionam fora do app". A causa era estrutural —
os atalhos de GRAVAR/PARAR/PAUSAR/MUDO existiam **só** como `AcceleratorTable`
do wx, e acelerador do wx só dispara com a JANELA FOCADA. Numa gravação o app
está minimizado ou atrás do jogo/navegador: a tecla chegava ao outro programa e
nunca ao recorder. Só as cenas (Ctrl+1..0), o F10 e o Ctrl+Shift+H estavam em
`RegisterHotKey` — por isso "alguns funcionam, os do app não".

O QUE ESTE MÓDULO GARANTE
=========================
1. **Registro global de verdade**: `RegisterHotKey` do Windows para todas as
   ações (gravar, parar, pausar, mudo, cena 1..10, bandeja, reabrir).
2. **`MOD_NOREPEAT`** (0x4000): segurar a tecla não dispara em rajada.
3. **`EVT_HOTKEY` do wx**, não `PeekMessage`. Medido nesta máquina: com
   `PeekMessage(PM_REMOVE)` num timer, o laço do wx NUNCA via a mensagem e o
   evento morria ali. Registrando por ctypes com o hwnd da janela, o wx entrega
   `EVT_HOTKEY` normalmente — inclusive com OUTRA janela em foco (provado).
4. **Falha visível**: `RegisterHotKey` devolve bool e `GetLastError()` diz se
   a combinação já estava tomada (erro 1409 = outra instância/programa). Cada
   registro loga OK/FALHOU com o motivo, e as colisões viram um aviso falado.
   Antes o retorno era descartado dentro de um `if` sem else — silêncio.
5. **Combinações do `config.ini`**: lê `[shortcuts]`; se o usuário trocar o
   atalho na aba Configurações, `recarregar()` desregistra e registra de novo.
6. **Desregistro de verdade** ao sair (processo na bandeja segurava as teclas).

FORMATO DO ATALHO NO CONFIG
===========================
Texto estilo Electron: `Control+Shift+R`, `Alt+F9`, `F10`, `Control+1`.
Aceita `Ctrl` como sinônimo de `Control`.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Optional

import wx

from engine.logs import logger

_log = logger("ui.hotkeys")

# ── constantes do Win32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Faixa de ids do app (0x0000-0xBFFF é livre para aplicações)
_ID_BASE = 0xB000

_MODS_TEXTO = {
    "control": MOD_CONTROL, "ctrl": MOD_CONTROL, "ctl": MOD_CONTROL,
    "shift": MOD_SHIFT, "alt": MOD_ALT, "win": MOD_WIN,
    "super": MOD_WIN, "meta": MOD_WIN,
}

# teclas nomeadas -> virtual-key code
_VK_TEXTO = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "escape": 0x1B, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pause": 0x13, "printscreen": 0x2C, "scrolllock": 0x91,
    "numlock": 0x90, "capslock": 0x14,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},      # F1=0x70
}

# Ações que o app registra globalmente: chave no config -> id
ACOES = {
    "start": _ID_BASE + 0,
    "stop": _ID_BASE + 1,
    "pause": _ID_BASE + 2,
    "mute": _ID_BASE + 3,
    "toggleAudio": _ID_BASE + 4,
    "toggleWindow": _ID_BASE + 5,
    "menu": _ID_BASE + 100,
    "reabrir": _ID_BASE + 101,
}

# Cenas: ids _ID_BASE+10 .. +19 (Ctrl+1..0)
_ID_CENA_BASE = _ID_BASE + 10


def _parse_vk(tecla: str) -> Optional[int]:
    """'R' -> 0x52, 'F10' -> 0x79, '1' -> 0x31."""
    k = (tecla or "").strip().lower()
    if not k:
        return None
    if k in _VK_TEXTO:
        return _VK_TEXTO[k]
    if len(k) == 1:
        c = k.upper()
        if "A" <= c <= "Z" or "0" <= c <= "9":
            return ord(c)
        if c in "[];,./\\'-=+`~!@#$%^&*()_{}|:\"<>?":
            # teclas de pontuação: o VK é o do caractere sem shift
            base = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
                    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
                    "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
                    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
                    "~": "`"}
            return ord(base.get(c, c).upper())
    return None


def parse_atalho(texto: str):
    """'Control+Shift+R' -> (modificadores, vk). None se não der para ler."""
    partes = [p.strip() for p in str(texto or "").split("+") if p.strip()]
    if not partes:
        return None
    mods = 0
    vk = None
    for p in partes:
        baixo = p.lower()
        if baixo in _MODS_TEXTO:
            mods |= _MODS_TEXTO[baixo]
        else:
            v = _parse_vk(p)
            if v is None:
                return None
            vk = v
    if vk is None:
        return None
    return mods, vk


def texto_atalho(mods: int, vk: int) -> str:
    """O inverso: (mods, vk) -> 'Control+Shift+R' (para exibir/logar)."""
    nomes = []
    if mods & MOD_CONTROL:
        nomes.append("Control")
    if mods & MOD_SHIFT:
        nomes.append("Shift")
    if mods & MOD_ALT:
        nomes.append("Alt")
    if mods & MOD_WIN:
        nomes.append("Win")
    for nome, cod in _VK_TEXTO.items():
        if cod == vk and len(nome) > 1:
            nomes.append(nome.upper() if nome.startswith("f") else nome.title())
            return "+".join(nomes)
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        nomes.append(chr(vk))
        return "+".join(nomes)
    nomes.append(f"VK{vk:#x}")
    return "+".join(nomes)


class GerenciadorAtalhos:
    """Registra/desregistra atalhos globais para uma janela wx.

    Uso:
        g = GerenciadorAtalhos(janela)
        g.registrar_acoes(cfg["shortcuts"], {"start": janela.p_gravacao.gravar,
                                             ...})
        g.registrar_cenas(10, on_cena)   # Ctrl+1..0
        ...
        g.encerrar()
    """

    def __init__(self, janela: wx.Window) -> None:
        self.janela = janela
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                            wintypes.UINT, wintypes.UINT]
        self.u32.RegisterHotKey.restype = wintypes.BOOL
        self.u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u32.UnregisterHotKey.restype = wintypes.BOOL

        self._registrados: dict[int, str] = {}      # id -> texto do atalho
        self._acoes: dict[int, Callable[[], None]] = {}
        self._bindados: set[int] = set()
        self._falhas: list[tuple[str, str]] = []    # (atalho, motivo)
        self._ativo = False

    # ------------------------------------------------------------ estado
    @property
    def registrados(self) -> dict[int, str]:
        return dict(self._registrados)

    @property
    def falhas(self) -> list[tuple[str, str]]:
        return list(self._falhas)

    def resumo(self) -> str:
        """Frase para falar/logar: quantos atalhos globais estão ativos."""
        n = len(self._registrados)
        if not self._falhas:
            return f"{n} atalho(s) global(is) ativo(s)."
        colididos = ", ".join(a for a, _ in self._falhas)
        return (f"{n} atalho(s) global(is) ativo(s). "
                f"Em uso por outro programa: {colididos}.")

    # ------------------------------------------------------------ registro
    def _hwnd(self) -> int:
        try:
            return int(self.janela.GetHandle() or 0)
        except Exception:
            return 0

    def _registrar_um(self, hid: int, mods: int, vk: int,
                      descricao: str) -> bool:
        hwnd = self._hwnd()
        if not hwnd:
            _log.error("atalho %s: janela sem hwnd", descricao)
            return False
        ctypes.set_last_error(0)
        ok = bool(self.u32.RegisterHotKey(hwnd, hid, mods | MOD_NOREPEAT, vk))
        if ok:
            if hid not in self._bindados:
                # o wx entrega EVT_HOTKEY pelo id — bind UMA vez por id
                self.janela.Bind(wx.EVT_HOTKEY,
                                 lambda ev, i=hid: self._disparar(i),
                                 id=hid)
                self._bindados.add(hid)
            self._registrados[hid] = texto_atalho(mods, vk)
            _log.info("atalho global OK: %s (%s)", texto_atalho(mods, vk),
                      descricao)
            return True
        err = ctypes.get_last_error()
        motivo = ("já registrado por outro programa" if
                  err == ERROR_HOTKEY_ALREADY_REGISTERED
                  else f"erro {err}")
        _log.error("atalho global FALHOU: %s (%s) -> %s",
                   texto_atalho(mods, vk), descricao, motivo)
        self._falhas.append((texto_atalho(mods, vk), motivo))
        return False

    def registrar_acoes(self, atalhos: dict, acoes: dict) -> None:
        """Registra o atalho de cada ação nomeada (start/stop/pause/...)."""
        self._falhas.clear()
        for nome, funcao in (acoes or {}).items():
            hid = ACOES.get(nome)
            if hid is None:
                continue
            texto = (atalhos or {}).get(nome, "")
            if not texto:
                continue
            analisado = parse_atalho(texto)
            if analisado is None:
                _log.error("atalho %r (ação %s) não entendido — ignorado",
                           texto, nome)
                self._falhas.append((str(texto), "formato não entendido"))
                continue
            mods, vk = analisado
            if self._registrar_um(hid, mods, vk, nome):
                self._acoes[hid] = funcao
        self._ativo = True

    def registrar_cenas(self, total: int, ao_cena: Callable[[int], None],
                        mods: int = MOD_CONTROL) -> None:
        """Ctrl+1..0 troca as cenas 1..10 GLOBALMENTE.

        Tecla NUA foi recusada de propósito: `RegisterHotKey` sem modificador
        sequestra a digitação de números no Windows INTEIRO (bug relatado).
        """
        total = max(0, min(10, int(total)))
        for i in range(total):
            vk = 0x30 if i == 9 else (0x31 + i)      # '0' -> 10ª cena
            hid = _ID_CENA_BASE + i
            if self._registrar_um(hid, mods, vk, f"cena {i + 1}"):
                self._acoes[hid] = (lambda idx=i: ao_cena(idx))

    def registrar_cena_extra(self, mods: int, vk: int,
                             ao_cena: Callable[[int], None],
                             indice: int) -> bool:
        """Atalho alternativo para uma cena (o usuário pode querer Alt+N)."""
        hid = _id_cena_alt(indice)
        if self._registrar_um(hid, mods, vk, f"cena {indice + 1} (alt)"):
            self._acoes[hid] = (lambda: ao_cena(indice))
            return True
        return False

    # ------------------------------------------------------------ disparo
    def _disparar(self, hid: int) -> None:
        acao = self._acoes.get(hid)
        if acao is None:
            _log.warning("EVT_HOTKEY sem ação: id=%s", hid)
            return
        _log.info("atalho disparado: id=%s (%s)", hid,
                  self._registrados.get(hid, "?"))
        try:
            acao()
        except Exception as e:
            _log.error("atalho %s falhou: %s: %s",
                       self._registrados.get(hid, hid), type(e).__name__, e)

    # ------------------------------------------------------------ ciclo
    def desregistrar(self) -> None:
        hwnd = self._hwnd()
        for hid in list(self._registrados):
            try:
                self.u32.UnregisterHotKey(hwnd, hid)
            except Exception:
                pass
        if self._registrados:
            _log.info("atalhos desregistrados: %d", len(self._registrados))
        self._registrados.clear()
        self._acoes.clear()
        self._ativo = False

    def recarregar(self, atalhos: dict, acoes: dict,
                   total_cenas: int = 0,
                   ao_cena: Optional[Callable[[int], None]] = None) -> None:
        """Aplica combinações novas (usuário trocou na aba Configurações)."""
        self.desregistrar()
        self.registrar_acoes(atalhos, acoes)
        if total_cenas and ao_cena is not None:
            self.registrar_cenas(total_cenas, ao_cena)

    def encerrar(self) -> None:
        self.desregistrar()


def _id_cena_alt(indice: int) -> int:
    return _ID_BASE + 40 + max(0, min(9, int(indice)))
