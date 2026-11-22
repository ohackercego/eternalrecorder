# Changelog

## 2.4.0 — o executável que realmente abre (PyInstaller), portátil e único

O exe da 2.3.1 **não abria**. Ao clicar:

```
cx_Freeze: Python error in main script (traceback unavailable)
Cannot import traceback module.
Exception: No module named 're'
Original Exception: No module named 're'
```

### Causa medida

O `dist_cxfreeze/lib/library.zip` saía com **184 entradas e nenhum módulo da
biblioteca padrão** — nem `re`, nem `json`, nem `traceback`, nem `encodings`.
Só pacotes de terceiros (`av`, `cffi`, `more_itertools`, `wx`, ...). O
interpretador embutido não tinha como importar `re`, então até o handler de
erro do cx_Freeze morreu — daí "traceback unavailable".

Não era falta de dependência nem caminho errado: o freezer simplesmente não
coletou a stdlib.

### Corrigido

- **Empacotamento migrado de cx_Freeze para PyInstaller 6.22.3.** O PyInstaller
  traz a stdlib no próprio bootstrap, então esse modo de falha não existe.
- **Dois formatos, como pedido:**
  - `Eternal Recorder (portatil).exe` — **arquivo único**, 90 MB. Para pendrive
    ou enviar por mensagem. Abre ~2 s mais devagar por extrair em `%TEMP%`.
  - `Eternal Recorder (portatil)\Eternal Recorder.exe` — **pasta** (onedir),
    229 MB. Abre na hora, sem extrair. É a mais rápida no uso diário.
- **O que o spec agora coleta de verdade:**
  - 81 MB de DLLs do libobs/ffmpeg (`pylibobs/_libs/windows/x86_64`, 27 DLLs)
  - 25 locales em `ui/locales` (sem eles a UI mostra `app.name` cru)
  - PortAudio do `sounddevice` (sem ela os bipes de `ui/tones.py` morrem mudos)
  - 17 hiddenimports para módulos carregados por nome
- **`scripts/empacotar.py`** agora falha de propósito se qualquer um dos dois
  executáveis não existir, e coloca os dois no ZIP.

### Medido depois

Ambos abrem sem erro:

```
17 atalho(s) global(is) ativo(s)
ícone da bandeja: instalado=True
Traceback / No module: 0 ocorrências
```

O `Eternal Recorder 2.4.0.zip` (292 MB, 5.561 entradas) contém os dois formatos
e o runtime Python para quem quiser rodar pelo `launcher.py`.

### Nota de ambiente

O Python 3.12 do sistema tinha um `pathlib` de terceiros que deixava o
PyInstaller instalar mas não executar ("pip uninstall pathlib"). O build usa um
venv limpo (`.venv-pyinstaller`, criado com `uv`) — por isso ele saiu.

## 2.3.1 — taxa de áudio, tarefas de UI e o .exe no release

Três problemas, todos vindos de um log real de gravação.

### Corrigido

- **Áudio gravado a 44100 Hz com o dispositivo em 48000.** O log do libobs
  mostrava a contradição na mesma sessão:

  ```
  info: audio settings reset:  samples per sec: 44100    <- errado
  info: WASAPI: Device 'Fones...' [48000 Hz] initialized <- o real
  ```

  Causa: `_taxa_audio_nativa()` chamava
  `sounddevice.query_devices(kind='output')`, que devolve o padrão do host de
  MAIOR prioridade do PortAudio — no Windows, o **MME**, que reporta 44100. O
  libobs não usa MME: as fontes `wasapi_*` abrem pelo **WASAPI**, a 48000. O
  contexto era configurado em 44100 com o aparelho entregando 48000, e o libobs
  reamostrava todo bloco (a voz "fininha, cortando e repetindo" de antes).

  Agora a taxa é lida do dispositivo **dentro do host WASAPI**. Medido depois:
  log diz `taxa de áudio: 48000 Hz (do host WASAPI; MME dizia 44100)` e o
  arquivo final tem `sample_rate=48000`, áudio 6.720 s contra vídeo 6.7167 s.

- **`error: UI task could not be queued, there's no UI task handler!` (×6 por
  gravação).** O libobs agenda `obs_queue_task(OBS_TASK_UI, ...)` quando uma
  fonte difere a destruição do recurso de GPU; sem handler registrado a tarefa é
  **descartada**, o destroy nunca roda e o recurso vaza — um erro por fonte, no
  fim de cada gravação. O `Motor` agora registra o handler em
  `_instalar_handler_de_ui()`, antes de criar qualquer fonte. Ele executa a
  tarefa na hora (este host não tem laço de UI do libobs) e o objeto do callback
  fica vivo em `self`, senão o cffi coleta e o libobs chama ponteiro morto.
  Medido: 0 ocorrências do erro no fluxo completo.

### O release agora SEMPRE leva o .exe do cx_Freeze

Pedido: "o release tem que ter sempre o .exe via cx_freeze". Antes o ZIP só
tinha o runtime embarcado + `.vbs`, o que obriga quem baixa a ter Python.

- `setup_cxfreeze.py` lê a versão do arquivo `VERSION` (estava hardcoded em
  `2.1.2`, então o exe saía com número errado) e inclui os 25 `ui/locales/*.json`
  como `include_files` — sem eles o exe abria com a chave crua na tela.
- `scripts/empacotar.py` copia `dist_cxfreeze/` para dentro do ZIP como
  `Eternal Recorder (exe)/` e **falha de propósito** se o exe não existir, em vez
  de gerar um release sem ele.

Testado: o exe abre com o título traduzido
(`Eternal Recorder — 1 monitor(es), 3 janela(s)`), não com `app.name`.

## 2.3.0 — pausa de verdade, atalhos globais e bipes audíveis

Três bugs relatados pelo usuário testando o app. Todos reproduzidos antes de
corrigir e validados com execução real depois.

### Corrigido

- **Pausar gravava o "parar ligado".** `pylibobs.Output.pause()` tem assinatura
  `pause(paused: bool = True)`: chamar `pause()` **sem argumento pausa**. O
  `retomar()` do motor fazia exatamente isso, então clicar em continuar pausava
  de novo. Resultado medido no fluxo real:

  ```
  PAUSAR  -> out.paused=True   active=True
  RETOMAR -> out.paused=True   active=True    <- nunca despausava
  t=9s    frames=62 (parado desde a pausa)
  ```

  Como o flag da UI era invertido antes da chamada e nunca conferido, o botão
  voltava a dizer "Pausar", o status dizia "Gravando" e os segundos continuavam
  andando com o arquivo congelado. Agora `pause(True)` / `pause(False)`
  explícitos, com confirmação por `saida.paused`: se o libobs não confirmar, a
  UI não mente.

- **Cronômetro andava durante a pausa.** O painel fazia `monotonic() - _t0`,
  que ignora pausa. A sessão agora guarda `tempo_pausado` e `pausa_desde`, e
  `Sessao.decorrido()` devolve o tempo GRAVADO. Prova: ~10,8 s de tempo real com
  ~4 s de pausa geraram arquivo de **6,73 s** — a pausa não entrou no vídeo.

- **Atalhos não funcionavam fora do app.** Gravar, parar, pausar e mudo
  existiam **só** como `AcceleratorTable` do wx, que dispara apenas com a janela
  focada — e quem grava está sempre em outro programa. Só as cenas (Ctrl+1..0),
  o F10 e o Ctrl+Shift+H usavam `RegisterHotKey`, o que explica o relato "alguns
  atalhos funcionam, os do app não". Novo módulo `ui/hotkeys.py` registra
  **todas** as ações globalmente, com `MOD_NOREPEAT`, combinações lidas do
  `config.ini`, colisão (erro 1409) logada e falada, e desregistro ao sair.

  O drenador antigo de `WM_HOTKEY` usava `PeekMessage(PM_REMOVE)` num `wx.Timer`
  e **engolia o evento antes de o wx vê-lo** — comprovado em bancada comparando
  os três caminhos. O registrador agora usa `EVT_HOTKEY`, que entrega o evento
  inclusive com outra janela em foco (medido).

- **Atalho trocado na aba Configurações só valia no próximo boot.** Agora
  `_recarregar_atalhos()` desregistra e registra na hora, e fala quantos estão
  ativos.

- **Nenhum som tocava em nenhum evento.** Duas causas somadas, e a segunda não
  estava documentada em lugar nenhum:
  1. `ui/tones.py` estava **no-op de propósito** (`ATIVO = False`, todas as
     funções `pass`) — resquício de quando o usuário pediu "pare TODO tipo de
     beeps". Nenhuma chamada podia soar.
  2. **`winsound` não existe no Python embarcado do app** (`python-embed` é
     build mínima, sem `_winsound`). Qualquer implementação com
     `import winsound` falhava dentro de um `except: pass` — silêncio absoluto,
     sem erro e sem log.

  Reescrito com síntese em `numpy` + `sounddevice` (presente no runtime),
  senoide com envelope de 5 ms, volume baixo, e fallback `winmm.PlaySoundW` via
  `ctypes`. Prova de que sai som de verdade: capturei o dispositivo padrão pelo
  `wasapi_output_capture` do próprio libobs e medi o pico por FFT — **660 Hz** na
  janela em que o tom tocou. "Não deu exceção" não é prova de áudio.

### Ordem dos tons

O tom sai pelo mesmo dispositivo que a captura grava, então a ordem por evento
foi ajustada para não contaminar o arquivo:

- **iniciar**: toca, espera o tom terminar, só então abre a captura
- **pausar**: pausa o output primeiro, toca depois
- **retomar**: toca, espera, então despausa
- **parar**: fecha o muxer, toca depois

Medido: os quatro tons tocaram e **nenhum** pico das frequências usadas
(660/880/520/360/700/470 Hz) apareceu no áudio do arquivo gravado.

### Empacotamento

- `scripts/empacotar.py` lia uma versão hardcoded (`2.1.1`) e gerava ZIP com o
  número errado; agora lê o arquivo `VERSION`.
- `eternal.spec`: `numpy` e `_sounddevice_data` como hiddenimports — sem eles os
  bipes morreriam no executável.

## 2.1.1 — quatro bugs do painel

Todos relatados pelo usuário testando o app, todos encontrados medindo.

### Corrigido

- **Leitor de tela falava `recorder.statusReady` ao dar Tab.** A chave não
  existia nos locales: `t()` devolvia a própria chave. Faltavam **13 chaves**
  (status, pasta, ganhos), não só essa. Agora o `pt-br` diz "Pronto" e uma
  verificação no fim do trabalho confirma que **nenhuma** das 81 chaves usadas
  no código está ausente.
- **O painel sempre anunciava "0 quadros".** O motor lia
  `saida.get_settings()["frames"]` — chave que não existe (o dicionário traz
  configuração, não contadores). A API certa é
  `obs_output_get_total_frames()`, lida **antes** do `release()`. Agora a UI
  diz 169 quando o arquivo tem 168.
- **Áudio repetia e travava.** Duas causas independentes:
  1. `set_audio()` sem argumento usa **44100 Hz**, mas o WASAPI entrega
     **48000**. O libobs reamostrava cada bloco e o buffer acumulava. Medido
     depois da correção: razão duração/tempo real **1,00**.
  2. No remux, `to_ndarray()` de um frame s16 estéreo devolve
     `(1, amostras*2)` — canais intercalados —, não `(canais, amostras)`.
     O código tratava como planar e o arquivo saía com o **dobro** da duração
     (5,013 s viravam 9,984 s; razão 1,992). Agora razão 0,996.
- **A câmera não aparecia em tela cheia nem em janela.** A caixa "Usar câmera"
  existia na aba Gravador, mas o valor dela **nunca era copiado para as
  Opções** — o motor recebia `camera_sobreposta=False` sempre. Agora a webcam
  entra na cena como fonte composta, com:
  - **4 cantos** selecionáveis (padrão: superior direito, como no outro app)
  - **3 tamanhos** (18% / 28% / 38% da largura)
  - **estilo de borda** (sólida / gradiente / neon)
  - posição e escala calculadas em pixels do canvas, proporção preservada

- **Gravações seguidas perdiam o áudio no começo.** O `parar()` soltava cena e
  saída, mas **nunca as fontes**. O ponteiro Python morria; o objeto libobs
  continuava vivo segurando o dispositivo WASAPI, e a gravação seguinte abria
  com `Device invalidated. Retrying` — o áudio reabria no meio. Cada gravação
  deixava um conjunto de fontes pendurado capturando em paralelo. Medido antes:
  a primeira gravação começava em `-inf` (silêncio). Depois de liberar as
  fontes e esperar 250 ms (o WASAPI devolve o dispositivo de forma assíncrona):
  **som desde o primeiro bloco** nas 5 gravações seguidas, e a razão de duração
  subiu de 0,979 para 0,991.

- **Cenas acumulavam até fechar o app.** `definir_cena()` anexava a cena em
  `self._refs` mesmo quando já havia sessão ativa — e `iniciar()` já tinha
  transferido `_refs` para a sessão. Resultado: a cena ficava órfã em `_refs`
  e só era destruída no `encerrar()`. Medido: **7 cenas de sessão** vivas ao
  mesmo tempo num teste de 7 gravações. Agora `definir_cena()` respeita a
  sessão ativa (`created` → `destroyed` emparelhados, `_refs` sempre 0).

### Adicionado

- `recorder.cameraPosition`, `recorder.cameraSize` e os 6 rótulos de canto e
  tamanho, em 25 idiomas.
- Verificação automática de chaves de tradução (todas as 81 usadas existem).

### Medido (Win10 19045.6466)

| Teste | Antes | Depois |
|---|---|---|
| Status ao dar Tab | `recorder.statusReady` | "Pronto" |
| Contador de quadros | sempre 0 | 169 (arquivo: 168) |
| Áudio 5 s | 9,98 s (razão 1,99) | 5,01 s (razão 1,00) |
| Câmera sobreposta | não aparecia | 4 cantos, YAVG 125 vs tela 224 |
| 5 gravações seguidas | 1ª em silêncio (`-inf`) | som desde o 1º bloco |
| Razão 5 gravações | 0,979 → caindo | 0,991 estável |

---

## 2.1.0 — migração para libobs

Esta versão **reescreve o motor inteiro**. Não é uma atualização incremental:
o Electron, o React, o Node e o sidecar Python saíram, e o núcleo do OBS Studio
(libobs, via pylibobs) entrou no lugar.

### Por que

Três recursos pedidos não existiam na pilha antiga:

- **Composição de cenas** — o Electron não tem canvas. Sobrepor câmera na tela
  exigia desenhar à mão em cada frame.
- **RTMP** — o capturekit não expõe saída de rede.
- **Áudio por processo** — o Electron não tem API para isso
  ([electron#54628](https://github.com/electron/electron/issues/54628), aberta
  desde 2023). O capturekit tinha o código, mas atrás de um gate de build
  (`>= 20348`) que bloqueava o Windows 10 — o mesmo código funciona em 19045,
  medido.

O libobs resolve as três com uma dependência.

### Adicionado

- **Cenas com composição real**: N fontes no mesmo quadro, cada uma com
  posição, escala e transformação. Câmera sobreposta à tela funciona de verdade.
- **Troca de cena ao vivo**: a gravação não para quando você muda de cena.
  Medido: YAVG 207 (monitor) → 121 (janela), arquivo contínuo.
- **RTMP nativo**: `rtmp_output` com `rtmp_custom` e presets `rtmp_common`
  (YouTube, Twitch, Facebook). Vários destinos ao mesmo tempo, entram e saem
  sem interromper a gravação.
- **Áudio por processo sem gambiarra**: `wasapi_process_output_capture` é uma
  fonte nativa. O monkeypatch do gate de build acabou.
- **20 tipos de fonte**: `monitor_capture`, `window_capture`, `game_capture`,
  `dshow_input`, `browser_source`, `ffmpeg_source`, `vlc_source`, `ndi_source`…
- **25 idiomas** com 185 chaves, zero divergência entre arquivos.

### Mudado

- **Interface**: wxPython com `wx.Accessible` por controle (IAccessible2
  nativo) em vez de React. NVDA, JAWS e Narrator leem sem plugin.
- **Uma fala por evento**: 1 ao iniciar, 1 ao parar, **zero durante**. O bug do
  leitor de tela anunciando o cronômetro a cada segundo não existe mais.
- **Estado no nome acessível**: o botão anuncia `GRAVAR: Tela inteira` e vira
  `Parar` ao gravar — nunca uma região viva.
- **Repositório**: 2,3 GB → **321 MB**. ZIP: 265 MB → **113 MB**.
- **Licença**: MIT → **GPL v2+**, exigida pelo libobs.

### Corrigido

Bugs encontrados medindo o produto, não revisando o código:

- **Gravação saía preta** (0 bytes durante a gravação, 12 KB no fim): a cena
  não estava definida no canal 0 do programa. Sem `obs_set_output_source(0,
  cena)` o libobs não renderiza nada.
- **Fonte parava de capturar sozinha**: o wrapper `Source` do pylibobs, ao sair
  de escopo, chama `obs_source_release` no `__del__` — a cena fica "com item"
  mas sem dados. Medido: 75 frames com 1 preto (referência viva) contra **75
  frames todos pretos** (sem referência).
- **`rate_control: "CRF"` quebrava o x264**: 8.648 bytes em 2,5 s com ele
  contra 1.805.018 bytes sem ele. O encoder entra em CRF sozinho.
- **MP3 saía com 0 bytes**: o muxer do libobs não produz áudio puro. Agora grava
  em `.mkv` temporário e o `engine/remux.py` converte no stop.
- **IDs de fonte errados**: `monitor_id` precisa do device path
  (`\\?\DISPLAY#...`), não de índice. `window` precisa de
  `titulo:classe:exe`. `video_device_id` precisa do path USB completo. Índice
  numérico faz a fonte abrir com `display: (0x0)` e gravar preto, sem erro.
- **Idioma não trocava**: os locales estavam em `src/locales` (pasta do
  Electron). Movidos para `ui/locales`.
- **`app.title` não existia** nos locales: a chave é `app.name`.
- **`.bat` chamava `pythonw.exe`**, que o Python embeddable não traz. Agora o
  lançador é um `.vbs` que roda `python.exe` com a janela escondida.

### Removido

- `electron/` inteiro (main, preload, sidecar, elevation)
- `src/` (React: componentes, hooks, locales)
- `package.json`, `node_modules`, Vite, ESLint, electron-builder
- `dist_electron/` e o ZIP de 265 MB
- `engine/recorder.py` (capturekit) e `engine/camera.py` (PyAV/dshow) —
  substituídos por `engine/motor_obs.py`
- `scripts/preparar-python.*` e `scripts/empacotar-zip.mjs` (Node)

### Medido nesta máquina

Windows 10 **19045.6466**, Ryzen 5 5500U, 1920×1080 @ 125% DPI:

| Teste | Resultado |
|---|---|
| Tela inteira, 5 s | 3713 KB, 150 frames, YAVG 207 |
| Janela, 4 s | 2863 KB, 120 frames, YAVG 121 |
| Câmera, 4 s | 3031 KB, 120 frames, YAVG 33 |
| Monitor + câmera sobreposta | 2865 KB, 120 frames, YAVG 201 |
| Troca de cena ao vivo | 207 → 121, sem parar |
| MP3 / WAV, 3 s | 142 KB (`mp3`) / 1040 KB (`pcm_s16le`) |
| Gravação pela UI | 1817 KB, 168 frames, YAVG 204 |
| **Do ZIP extraído** | **3027 KB, 120 frames, 4,00 s, YAVG 195** |
| **Do ZIP, pela UI (Python 3.14)** | **2158 KB, 199 frames, 6,64 s, YAVG 209** |

Os quatro modos geram arquivos com md5 diferente — conteúdo distinto, não a
mesma captura reciclada.

### Limitações conhecidas

- Só Windows.
- Câmera a ~10 fps com pouca luz (limitação do hardware testado).
- Atalhos globais só com a janela focada.
- ~1 s de preto ao trocar de cena (o WGC reaquece).
- `stats.perdidos` sempre 0: o libobs não reporta descarte por fonte.

---

## Versões anteriores

A 2.0 e anteriores usavam Electron + React + sidecar Python. O histórico delas
está no git (tag `v2.0.0`); os números e decisões daquela arquitetura não se
aplicam mais a esta.
