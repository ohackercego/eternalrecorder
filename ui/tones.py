"""Sons de estado da gravação — DESATIVADO. Nenhum beep é tocado.

HISTÓRICO
=========
1. O app tocava bipes com `winsound.Beep` — a campainha do PC, onda quadrada,
   volume máximo. O usuário pediu para retirar ("tira esse beep").
2. Implementei tons senoidais suaves em memória com PlaySound.
3. O usuário pediu de novo, de outra forma: "pare TODO tipo de beeps".

DECISÃO — NENHUM SOM
====================
As funções continuam existindo (inicio, pausa, retomada, fim, salvo, erro),
mas são no-op: o painel chama e nada toca. Motivos:

- O feedback de estado já existe por FALA (NVDA lê "gravação iniciada",
  "pausada", "encerrada", "arquivo salvo") — e fala é o canal correto para
  quem usa leitor de tela, o público principal deste app.
- Qualquer tom toca no MESMO dispositivo que está sendo gravado. Um bipe no
  início ou no fim entra no arquivo — é contaminação do conteúdo gravado.
- Silêncio é o estado neutro de um gravador de áudio.

Manter as funções como no-op (em vez de apagar) preserva a integração: a UI
continua chamando, e reativar sons no futuro é editar só este módulo, não
caçar nove chamadas espalhadas. A implementação anterior está no histórico
do git.
"""
from __future__ import annotations

# Nenhum som é tocado. A fala (ui.speech) é o único feedback sonoro do app.

ATIVO = False


def inicio() -> None:
    """No-op: sem som. A fala anuncia o início."""


def pausa() -> None:
    """No-op: sem som. A fala anuncia a pausa."""


def retomada() -> None:
    """No-op: sem som. A fala anuncia a retomada."""


def fim() -> None:
    """No-op: sem som. A fala anuncia o fim."""


def salvo() -> None:
    """No-op: sem som. A fala anuncia o arquivo salvo."""


def erro() -> None:
    """No-op: sem som. A fala anuncia o erro."""


def parada() -> None:
    """No-op: sem som."""


def encerrada() -> None:
    """No-op: sem som."""


# rótulos textuais, para a UI mostrar no lugar do som (acessibilidade)
LEGENDA = {
    "inicio": "Gravação iniciada",
    "pausa": "Gravação pausada",
    "retomada": "Gravação retomada",
    "fim": "Gravação encerrada",
    "salvo": "Arquivo salvo",
    "erro": "Erro na gravação",
}

ESTADOS = ("inicio", "pausa", "retomada", "fim", "salvo", "erro")


def sequencia(nome: str) -> tuple:
    """Compatibilidade: sempre vazio — não há mais tons."""
    return ()


def wav(nome: str) -> bytes:
    """Compatibilidade: sempre vazio — não há mais tons."""
    return b""
