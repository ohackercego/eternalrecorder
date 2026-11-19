# Eternal Recorder

Gravador de tela, janela e câmera **100% acessível para leitores de tela** (NVDA, JAWS), em Python puro com libobs.

**Versão 2.1.2** · Windows 10/11 · GPL v2

---

## Por que o Eternal Recorder existe

A maioria dos gravadores de tela não funciona com leitores de tela: botões sem nome, estados que não são anunciados, teclado que não navega. O Eternal Recorder foi construído **do zero** com acessibilidade como requisito — cada controle tem nome, cada estado é falado, cada função tem atalho de teclado.

## Recursos

### Gravação
- **Tela inteira** (qualquer monitor)
- **Janela específica** — com áudio **daquele aplicativo** (process loopback), não do sistema
- **Câmera** com sobreposição em qualquer canto e tamanho
- **Somente áudio** (mp3, wav, flac)
- Mic + áudio do sistema, ou cada um separadamente
- Ganho de áudio **opcional** — por padrão segue o volume do mixer do Windows
- Pausar, retomar, mutar microfone ao vivo

### Cenas (presets) com troca ao vivo
- Cada cena salva: fonte de vídeo, alvo, **áudio**, câmera sobreposta (canto + tamanho)
- **Ctrl+1 a Ctrl+0** troca de cena **ao vivo, em qualquer lugar** — durante a gravação ou a transmissão
- **1-9 e 0** trocam com a janela do app focada
- A troca muda o vídeo **e** o áudio na hora, no mesmo arquivo

### Transmissão
- RTMP ao vivo (Twitch, YouTube, Facebook, custom) enquanto grava
- A transmissão usa o preset da cena ativa

### Acessibilidade
- Cada controle com nome acessível — nada de botão anônimo
- Estados falados: gravando, pausada, encerrada, arquivo salvo, erro
- Navegação por Tab completa, incluindo campos somente leitura
- Modo cena anunciado ao ativar, com o resumo do preset
- Fala por NVDA/JAWS (accessible_output2)

### Bandeja e menu
- Fechar minimiza para a **bandeja** (configurável)
- Menu da bandeja: Reabrir · **Projeto no GitHub** · Sair
- **F10** abre o menu de qualquer lugar
- **Alt+S** abre o menu Sistema da janela

---

## Atalhos

| Tecla | Ação |
|---|---|
| `Ctrl+Shift+R` | Gravar / parar |
| `Ctrl+Shift+S` | Parar |
| `Ctrl+Shift+P` | Pausar / retomar |
| `Ctrl+Shift+M` | Mutar microfone |
| `Ctrl+Shift+A` | Marcar/desmarcar áudio do sistema |
| `Ctrl+1` … `Ctrl+0` | **Trocar de cena ao vivo** (qualquer lugar) |
| `1` … `9`, `0` | Trocar de cena (janela focada) |
| `Ctrl+Shift+H` | Reabrir do modo bandeja |
| `F10` | Menu (Reabrir / GitHub / Sair) |
| `Alt+S` | Menu Sistema (janela focada) |

---

## Instalação

Baixe o **zip** da [última release](https://github.com/ohackercego/eternalrecorder/releases), extraia e execute `Eternal Recorder.exe`.

Não precisa de instalação, Python ou Node.

## Código-fonte

O projeto é **Python puro**:

```
launcher.py            entrada
ui/                    wxPython acessível (app, painéis, fala, i18n)
engine/motor_obs.py    motor libobs (cenas, fontes, encoders, RTMP)
engine/remux.py        conserta container no stop (MKV -> MP4/MP3)
engine/config.py       configurações
engine/logs.py         logging em %LOCALAPPDATA%\EternalRecorder\logs
```

### Desenvolvimento

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

Dependências principais: wxPython, pylibobs, PyAV, sounddevice, numpy, accessible_output2.

### Idiomas

25 idiomas incluídos (pt-BR, en, es, ru, fr, de, zh, ja, ar, he, entre outros). Troque na aba Configurações — a interface é reconstruída no idioma novo na hora.

---

## Licença

**GPL v2** — compatível com a licença do libobs. Veja [LICENSE](LICENSE).

## Autor

Juan Mathews Rebello Santos — [GitHub](https://github.com/ohackercego)
