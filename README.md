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

## Atalhos e teclas — o que funciona de verdade

### Trocar de cena

| Tecla | Onde funciona | O que faz |
|---|---|---|
| **1** a **9** e **0** | com a janela do Eternal em foco | troca para a cena 1-10 **na hora** — muda o vídeo e o áudio na gravação em andamento |

> **Importante:** as teclas de 1 a 0 são a forma **confiável** de trocar de cena.
> A tecla **0** ativa a cena 10.
> Precisa do **Modo Cena marcado** na aba Gravação e de uma cena ativada na aba Cenas.

Ao trocar, o app **fala** qual cena entrou: "Cena 2 aplicada ao vivo... Áudio: áudio do sistema".

### Gravação

| Tecla | Ação |
|---|---|
| `Ctrl+Shift+R` | Gravar / parar |
| `Ctrl+Shift+S` | Parar |
| `Ctrl+Shift+P` | Pausar / retomar |
| `Ctrl+Shift+M` | Mutar microfone |
| `Ctrl+Shift+A` | Marcar/desmarcar áudio do sistema |
| `Ctrl+Shift+H` | Reabrir do modo bandeja |

### Menu

| Tecla | Ação |
|---|---|
| `Alt+S` | Abre o menu Sistema (Reabrir / GitHub / Sair) |
| `F10` | Abre o mesmo menu, global |

---

## Guia das funções — para quem nunca usou um gravador

### Aba Gravação

**Tela para gravar.** Escolha o que capturar:
- *Tela cheia* — grava o monitor inteiro. Se você tiver dois monitores, escolha qual.
- *Janela específica* — grava só uma janela (um jogo, um navegador). O áudio da janela vem **daquele programa**, não do PC todo: se tocar música em outro programa, ela NÃO entra.
- *Somente câmera* — grava só a webcam, em tela cheia.

**Microfone.** Marque para a sua voz entrar na gravação. Desmarque para gravar só o que toca no PC.

**Áudio do sistema.** Marque para capturar tudo que toca no computador (vídeos, jogos, chamadas). No modo janela, o áudio vem só da janela escolhida.

**Usar câmera.** Coloca sua webcam num quadro pequeno no canto da gravação — o clássico "rosto no canto". Você escolhe o canto e o tamanho.

**Formato.** MP4 abre em qualquer lugar; MKV é o mais resistente a falhas; WebM é mais leve. Para só áudio: MP3 (pequeno), WAV (qualidade máxima), FLAC (sem perdas).

**Modo cena.** Marque para usar as cenas da aba Cenas. Desmarcado, as teclas de cena não fazem nada.

O botão grande inicia e para. Enquanto grava, as opções ficam travadas — pare a gravação para mudar.

### Aba Cenas

Uma cena é um **preset completo**: qual tela/janela/câmera gravar, qual áudio usar, onde a câmera fica.

1. Escolha o vídeo, o áudio e a câmera no quadro "Preset da cena"
2. Digite um nome e clique **Adicionar cena**
3. A cena ganha um número: é a tecla que ativa ela (1 a 9, 0 para a 10ª)

Durante a gravação, aperte o número da cena e **tudo muda na hora, no mesmo arquivo** — trocou de tela pra janela, o áudio da janela entra e o microfone sai (ou fica, dependendo do que a cena diz).

**Salvar no selecionado** atualiza a cena que está selecionada com o preset atual.

**Ativar cena** aplica a cena selecionada — o mesmo que apertar o número.

### Aba Transmissão

Manda a gravação **ao vivo** para Twitch, YouTube ou Facebook enquanto grava.

1. Escolha a plataforma (a URL se preenche sozinha)
2. Cole a **chave de stream** (o painel da plataforma te dá)
3. Clique **Adicionar destino**
4. Inicie a gravação na aba Gravação
5. Clique **Iniciar transmissão**

O que vai ao ar é o preset da cena ativa. O quadro "O que vai ao ar" mostra exatamente isso.

### Aba Configurações

**Qualidade.** FPS (30 é o normal), resolução (Fonte usa a resolução nativa da tela), vídeo e áudio em kbps — mais = melhor qualidade e arquivo maior.

**Ganho do microfone / do sistema.** Deixe em **"seguir o sistema (recomendado)"**: o volume que você ajusta no Windows é o que grava. Os números (6, 12, 18 dB) multiplicam o volume — só use se o áudio ficou baixo mesmo com o Windows no máximo.

**Pasta das gravações.** Onde os arquivos são salvos. O botão anuncia a pasta atual e abre o seletor.

**Comportamento ao fechar.** "Ir para a bandeja" mantém o app rodando em segundo plano quando você fecha (a gravação continua). "Sair" encerra de verdade.

**Atalhos.** Teclas das funções principais — clique para trocar.

**Idioma.** 25 idiomas. Trocou, a interface reconstrói na hora.

### Bandeja e menu

Ao fechar, o app vai para a **bandeja** (ícone perto do relógio) e a gravação continua. Clique no ícone para reabrir. Clique com o **botão direito** para o menu:

- **Reabrir Eternal Recorder** — abre a janela
- **Projeto no GitHub** — abre este repositório no navegador
- **Sair** — encerra de verdade

O menu também abre com **Alt+S** (janela focada) ou **F10** (qualquer lugar).

### Solução de problemas

O app registra tudo em `%LOCALAPPDATA%\EternalRecorder\logs` (um arquivo por dia). Se algo não funcionar, esse arquivo mostra exatamente o que o app tentou fazer — anexe ele no relatório do bug.

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
