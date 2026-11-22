# Eternal Recorder

A **fully screen-reader accessible** (NVDA, JAWS) screen, window and camera recorder for Windows, built in pure Python with libobs.

**Version 2.4.0** · Windows 10/11 · GPL v2 · [Baixar em português](#português)

## Downloads

Get the latest version from the [Releases page](https://github.com/ohackercego/eternalrecorder/releases/latest):

- **Eternal Recorder (zip)** — extract and pick one:
  - `Eternal Recorder (portatil).exe` — **single file**, 90 MB. Nothing to unpack first; best for a USB stick or sending to someone.
  - `Eternal Recorder (portatil)\Eternal Recorder.exe` — **folder** build, 229 MB. Opens instantly (no unpacking); best for daily use on the same PC.

  Both are built with **PyInstaller** and need no Python installed. (2.3.1 shipped a cx_Freeze exe that failed on launch with `No module named 're'` — see the changelog.)
- **Eternal Recorder (single executable)** — one standalone `.exe` (experimental)

No installer, no Python, no Node required.

## Highlights

- **Live scene switching**: press **1–9 and 0** (with the app window focused) or **Ctrl+1–0 from anywhere** to switch scenes instantly — video **and** audio change in the same recording file
- **Window audio**: records the audio of the chosen application only, not the whole system
- **Optional audio gain**: by default follows the Windows mixer volume
- **Camera overlay**: picture-in-picture webcam in any corner and size
- **Streaming**: RTMP live to Twitch, YouTube or Facebook while recording
- **25 languages** with full translation
- **Tray**: closing minimizes to the tray; recording keeps running
- **libobs engine** (pylibobs): real composition, hardware encoders, RTMP

## Shortcuts

| Key | Where | Action |
|---|---|---|
| **1–9, 0** | app window focused | switch to scene 1–10 (0 = scene 10) |
| `Ctrl+Shift+R` | global | record |
| `Ctrl+Shift+S` | global | stop |
| `Ctrl+1` … `Ctrl+0` | global | switch to scene 1–10 (0 = scene 10) |
| `Ctrl+Shift+P` | global | pause / resume |
| `Ctrl+Shift+M` | global | mute microphone |
| `Ctrl+Shift+A` | global | toggle system audio |
| `Ctrl+Shift+H` | global | reopen from tray |
| `Alt+S` | app window focused | System menu (GitHub, Quit) |
| `F10` | global | tray menu (GitHub, Quit) |

## Audio feedback

Short beeps mark start, pause, resume and stop, so you know the state without
looking at the screen. They are synthesized to a low volume and scheduled so
they never land inside the recording: the start tone finishes **before** capture
opens, the pause tone plays **after** the output is paused, and the stop tone
plays **after** the MP4 is closed. If sound is unavailable, the app says so in
the log (`er.ui.tones`) instead of failing silently.

## Feature guide

### Recording tab

Choose what to capture:

- **Full screen** — records an entire monitor (pick which one).
- **Specific window** — records a single window (a game, a browser). Window audio comes **from that program**, not the whole PC.
- **Camera only** — full-screen webcam recording.

**Microphone** adds your voice; **system audio** captures what plays on the PC. **Use camera** overlays your webcam picture-in-picture (corner and size configurable). **Format**: MP4 (universal), MKV (crash-resilient), WebM (light); audio-only: MP3, WAV, FLAC.

**Scene mode** enables the scene keys. While recording, options are locked — stop to change them.

### Scenes tab

A scene is a **complete preset**: which screen/window/camera, which audio, where the camera overlay goes.

1. Configure the preset, type a name, click **Add scene**
2. The scene gets a number — that's the key that activates it (1–9, 0 for the 10th)

During a recording, press the scene number and **everything switches live, in the same file**.

### Streaming tab

Go live on Twitch, YouTube or Facebook while recording: pick the platform, paste your **stream key**, add the destination, start recording, then click **Start streaming**. The scene selector on the tab chooses what goes on air.

### Settings tab

- **Quality**: FPS, resolution, video/audio bitrate
- **Gain**: keep "follow the system (recommended)" — the Windows mixer volume is what gets recorded
- **Recording folder**: where files are saved
- **Close behavior**: "go to tray" (recording continues) or "exit"
- **Shortcuts**: click to remap
- **Language**: 25 languages, applied instantly

### Tray and menu

Closing the app hides it to the **tray** (icon near the clock) and recordings keep going. Right-click the icon for the menu: **GitHub project** (opens this repository) and **Quit**. Also available via `Alt+S` (focused) or `F10` (global).

## Troubleshooting

The app logs everything to `%LOCALAPPDATA%\EternalRecorder\logs` (one file per day). When something goes wrong, that file shows exactly what the app tried — attach it to bug reports.

## Build from source

Requires Python 3.12+:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

### Packaging (PyInstaller)

The spec builds **both** formats in one run — the folder build and the single file:

```bash
pip install pyinstaller
python -m PyInstaller eternal_recorder.spec --noconfirm \
    --distpath dist_pyi --workpath build_pyi
```

That writes:

| Output | What it is | Size |
|---|---|---|
| `dist_pyi/Eternal Recorder/` | folder build (onedir) — opens instantly, no unpacking | ~229 MB |
| `dist_pyi/Eternal Recorder (portatil).exe` | single file (onefile) — for a USB stick | ~90 MB |

Neither needs Python installed on the target machine.

Then the release ZIP:

```bash
python scripts/empacotar.py --sem-deps
```

`empacotar.py` **refuses to build** if either executable is missing, and puts both
in the ZIP. It no longer uses cx_Freeze: that build produced an exe that died on
launch with `No module named 're'` because its `library.zip` shipped without the
Python standard library (see the changelog for 2.4.0).

> If `pyinstaller` installs but will not run, your Python may have a third-party
> `pathlib` shadowing the standard one (`pip uninstall pathlib`). A clean venv
> avoids it.

## Portuguese (original)

<details>
<summary><b>Leia-me em português</b></summary>

# Eternal Recorder

Gravador de tela, janela e câmera **100% acessível para leitores de tela** (NVDA, JAWS), em Python puro com libobs.

## Destaques

- **Troca de cena ao vivo**: teclas **1–9 e 0** (janela em foco) trocam de cena na hora — vídeo **e** áudio mudam no mesmo arquivo
- **Áudio da janela**: captura o áudio do aplicativo escolhido, não do sistema
- **Ganho opcional**: por padrão segue o volume do mixer do Windows
- **Câmera sobreposta**: webcam em quadro no canto que você escolher
- **Transmissão**: RTMP ao vivo para Twitch, YouTube ou Facebook
- **25 idiomas** com tradução completa
- **Bandeja**: fechar minimiza; a gravação continua
- **Motor libobs** (pylibobs): composição real, encoders de hardware, RTMP

## Atalhos

| Tecla | Onde | Ação |
|---|---|---|
| **1–9, 0** | janela em foco | troca para a cena 1–10 |
| `Ctrl+Shift+R` | global | gravar / parar |
| `Ctrl+Shift+S` | global | parar |
| `Ctrl+Shift+P` | global | pausar / retomar |
| `Ctrl+Shift+M` | global | mutar microfone |
| `Ctrl+Shift+A` | global | áudio do sistema |
| `Ctrl+Shift+H` | global | reabrir da bandeja |
| `Alt+S` | janela em foco | menu Sistema (GitHub, Sair) |
| `F10` | global | menu da bandeja |

## Guia das funções

**Aba Gravação**: tela cheia (escolhe o monitor), janela específica (o áudio vem **daquele programa**) ou somente câmera. Microfone e áudio do sistema marcam o que entra. **Usar câmera** põe a webcam em quadro no canto. Formatos: MP4, MKV, WebM; só áudio: MP3, WAV, FLAC. **Modo cena** liga as teclas de cena. Opções travam durante a gravação.

**Aba Cenas**: uma cena é um **preset completo**. Configure, dê um nome, **Adicionar cena**. O número da cena é a tecla que ativa (1–9, 0 para a 10ª). Na gravação, aperte o número e **tudo muda ao vivo, no mesmo arquivo**.

**Aba Transmissão**: escolha a plataforma, cole a **chave de stream**, adicione o destino, inicie a gravação e clique **Iniciar transmissão**. O seletor de cena da própria aba escolhe o que vai ao ar.

**Aba Configurações**: FPS, resolução, bitrate; ganho ("seguir o sistema" é o recomendado); pasta das gravações; fechar vai para a bandeja ou sai; atalhos clicáveis; 25 idiomas na hora.

**Bandeja**: fechar esconde o app (gravação continua). Botão direito no ícone: **Projeto no GitHub** e **Sair**. Também com `Alt+S` ou `F10`.

## Solução de problemas

O app registra tudo em `%LOCALAPPDATA%\EternalRecorder\logs` (um arquivo por dia). Anexe o arquivo do dia no relatório do bug.

## Licença

GPL v2 — see [LICENSE](LICENSE).

</details>
