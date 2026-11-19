"""Saída de fala única do Eternal Recorder.

Todo anúncio do app passa por aqui — mesma ideia do
`AccessibleSpeechOutput` do WinZapp_Python, que centraliza a fala num objeto
para que os interruptores de acessibilidade valham em todos os pontos de
chamada de uma vez.

Por que não `aria-live` (o bug que motivou este módulo):
no build Electron, um bloco com `aria-live="polite"` continha o cronômetro da
gravação. O leitor de tela anunciava "gravando 0:01", "0:01", "0:02"... a cada
segundo, sem parar. Em wxPython não existe região viva: quem fala é este
objeto, sob demanda, e o estado (tempo, nível) fica no nome acessível do
controle — lido quando o usuário foca nele, não empurrado.
"""
from __future__ import annotations

from typing import Callable, Optional


class Speech:
    """Fala com dois interruptores, como no WinZapp.

    - `enabled` (padrão True): interruptor mestre. Desligado, nada é falado —
      o usuário usa só a interface visual.
    - `sapi_fallback` (padrão True): quando False, só fala por leitor de tela
      real (NVDA, JAWS, ZDSR...). O SAPI sempre reporta `is_active() == True`,
      então sem esta opção o app falaria por cima de quem não tem leitor.

    O leitor é consultado a cada chamada, não só na inicialização: desligar o
    NVDA no meio da sessão silencia o app na hora.
    """

    def __init__(self, enabled: bool = True, sapi_fallback: bool = True,
                 on_speak: Optional[Callable[[str], None]] = None) -> None:
        self.enabled = enabled
        self.sapi_fallback = sapi_fallback
        self._on_speak = on_speak
        self._auto = None
        self._erro: Optional[str] = None
        self._iniciar()

    def _iniciar(self) -> None:
        try:
            from accessible_output2.outputs import auto
            self._auto = auto.Auto()
        except Exception as e:            # pacote ausente não pode derrubar o app
            self._erro = f"{type(e).__name__}: {e}"

    @property
    def leitor(self) -> str:
        """Nome do leitor que está sendo usado, para exibir nas configurações."""
        if self._erro:
            return f"indisponível ({self._erro})"
        if self._auto is None:
            return "nenhum"
        try:
            saida = self._resolver()
            return type(saida).__name__ if saida else "nenhum"
        except Exception:
            return "nenhum"

    def _resolver(self):
        if not self.enabled or self._auto is None:
            return None
        if self.sapi_fallback:
            return self._auto.get_first_available_output()
        # só leitor de tela de verdade: SAPI é `is_system_output()`
        for saida in getattr(self._auto, "outputs", ()):
            try:
                if not saida.is_system_output() and saida.is_active():
                    return saida
            except Exception:
                continue
        return None

    def falar(self, texto: str, interrupt: bool = False) -> None:
        """Fala um texto. `interrupt` corta o que estiver sendo dito."""
        if not texto:
            return
        if self._on_speak is not None:
            try:
                self._on_speak(texto)
            except Exception:
                pass
        saida = self._resolver()
        if saida is None:
            return
        try:
            if interrupt and hasattr(saida, "silence"):
                saida.silence()
            saida.speak(texto)
        except Exception:
            pass

    def silenciar(self) -> None:
        """Corta a fala em andamento (não impede as próximas)."""
        saida = self._resolver()
        if saida is not None and hasattr(saida, "silence"):
            try:
                saida.silence()
            except Exception:
                pass
