# Eternal Recorder — arquitetura (2.1)

Data: 2026-11-17 · Estado: **medido nesta máquina**, não baseado em README.

## A decisão: libobs como biblioteca

O motor é o **libobs** — o núcleo do OBS Studio — via
[pylibobs](https://github.com/norihiro/pylibobs). A UI é wxPython com
`wx.Accessible` por controle.

Três recursos pedidos pelo usuário não existiam nas pilhas anteriores:

| Recurso | Por que Electron + capturekit não fazia |
|---|---|
| Composição de cenas | Electron não tem canvas de composição; sobrepor câmera exigia desenhar por frame |
| RTMP | capturekit não expõe saída de rede |
| Áudio por processo | Electron não tem API ([#54628](https://github.com/electron/electron/issues/54628)); o capturekit tinha o código atrás de um gate `build >= 20348` que bloqueia o Windows 10 |

O libobs tem as três. Uma dependência substituiu três camadas.

## Comparação medida (não estimada)

| | capturekit 0.1.0 | pylibobs 33.0.0.2 |
|---|---|---|
| monitor / janela | sim | sim |
| câmera | **não** (`NotImplementedError`) | `dshow_input` |
| composição | **não** | N fontes por cena, com posição/escala/crop |
| RTMP | **não** | `rtmp_output`, `rtmp_custom`, `rtmp_common` |
| áudio por processo | sim, mas atrás de gate de build | `wasapi_process_output_capture` nativo |
| tipos de fonte | 2 | **20** |
| licença | MIT | **GPL v2+** |

O gate do capturekit era uma linha: `return windows_build() >= 20348`. Nesta
máquina (19045) o código abaixo funcionava — o monkeypatch mediu 83.495 bytes /
-29,6 dB de um processo específico. Com o libobs o gate deixa de existir.

## Estrutura

```
launcher.py               entrada; injeta sys.path; abre a UI
engine/
  motor_obs.py            OBSContext, cenas, fontes, encoders, RTMP, remux no stop
  remux.py                troca container/codec quando a extensão promete outro
ui/
  app.py                  janela, 4 abas, AcceleratorTable
  painel_gravacao.py      fonte, áudio, formato, REC/PAUSE/MUTE/STOP
  painel_cenas.py         criar/remover cenas, adicionar fontes
  painel_config.py        fps, resolução, bitrate, ganho, pasta, atalhos, idioma
  painel_transmissao.py   destinos RTMP, entrar/sair ao vivo
  accessible.py           wx.Accessible (IAccessible2)
  speech.py               fala única por evento
  tones.py                sons de início/fim/erro
  i18n.py                 25 locales, 185 chaves
```

## O ciclo de gravação

```python
ctx = OBSContext(); ctx.__enter__()
ctx.set_video(w, h, fps_num); ctx.set_audio(); ctx.load_modules()

cena   = Scene.create(nome)
fonte  = Source.create(kind, nome, settings)   # settings com os IDs de device
item   = cena.add(fonte)                       # posição/escala ficam no item
venc, aenc = encoders(...)
out    = Output.create("ffmpeg_muxer", "gravacao", {"path": ..., "format": ...})
out.set_video_encoder(venc); out.set_audio_encoder(aenc)

obs_set_output_source(0, cena.as_source()._ptr)   # ← obrigatório
out.start()
```

`obs_set_output_source(0, ...)` é o canal 0 do programa: é o que a saída
renderiza. `pylibobs.scene` não expõe `set_current_scene`, então a chamada vai
pelo `_ffi.get_lib()`.

## As três armadilhas (todas custaram horas)

### 1. Referência Python viva

O wrapper `Source` do pylibobs chama `obs_source_release` no `__del__`. Se a
variável Python sair de escopo, a fonte **para de entregar quadro** — a cena
continua com o item, sem erro, e o arquivo sai preto.

Medido, mesma sessão, mesma fonte:

| | frames | pretos | mediana YAVG |
|---|---|---|---|
| referência viva | 75 | 1 (aquecimento) | 213 |
| sem referência | 75 | **75** | **16** |

`Sessao.objetos` e `Motor._refs` existem só para segurar essas referências.

### 2. `rate_control` quebra o x264

| settings | bytes em 2,5 s |
|---|---|
| `{'crf': 20}` | **1.805.018** |
| `{'crf': 20, 'rate_control': 'CRF'}` | **8.648** (tela preta) |

Sem `rate_control` o encoder entra em CRF sozinho. Para CBR, mandar
`rate_control: "CBR"` junto com `bitrate` funciona.

### 3. O muxer não faz áudio puro

`format: "mp3"` gera arquivo de 0 bytes. A solução: gravar em `.mkv` temporário
e converter no `parar()` via `engine/remux.py` (PyAV).

## IDs de fonte (não são números)

| Fonte | Campo | Formato |
|---|---|---|
| `monitor_capture` | `monitor_id` | `\\?\DISPLAY#LEN9051#5&27df25d&0&UID256#{e6f07b5f-...}` |
| `window_capture` | `window` | `titulo:classe:exe` |
| `dshow_input` | `video_device_id` | `Integrated Camera:\\?\usb#vid_04f2&pid_b725...` |
| `wasapi_process_output_capture` | `window` | `pid:executavel` |

Passar índice numérico faz a fonte abrir com `display: (0x0)` no log e gravar
preto, **sem levantar erro**. Os valores válidos saem de
`Source.create(kind, ..., {}).get_properties()` → `p.items`.

## Acessibilidade

`wx.Accessible` por controle expõe IAccessible2 direto da janela — NVDA lê sem
plugin. Regras:

- **estado no nome acessível**, nunca em região viva (sem `aria-live`)
- **uma fala por evento** — 1 ao iniciar, 1 ao parar, 0 durante
- **som antes da fala** — quem ouve entende o que mudou de estado
- **modos exclusivos coerentes** — "só câmera" esconde controles de tela

## Números medidos

Windows 10 19045.6466 · Ryzen 5 5500U · 1920×1080 @ 125%

| Teste | Resultado |
|---|---|
| Monitor 5 s | 3713 KB, 150 f, YAVG 207 |
| Janela 4 s | 2863 KB, 120 f, YAVG 121 |
| Câmera 4 s | 3031 KB, 120 f, YAVG 33 |
| Monitor + câmera | 2865 KB, 120 f, YAVG 201 |
| Troca de cena | 207 → 121, contínuo |
| MP3 3 s | 142 KB, codec `mp3` |
| WAV 3 s | 1040 KB, codec `pcm_s16le` |
| UI completa | 1817 KB, 168 f, YAVG 204 |
| ZIP extraído | 3027 KB, 120 f, 4,00 s, YAVG 195 |
| ZIP pela UI (Py 3.14) | 2158 KB, 199 f, 6,64 s, YAVG 209 |

Os 4 modos têm md5 diferente — conteúdo distinto.

## Licença

GPL v2+ (herdada do libobs). O código da 2.0 era MIT; distribuir com o libobs
obriga GPL. Alternativa LGPL seria GStreamer, ao custo de reescrever toda a
camada de captura.

## O que ficou de fora

- **`RegisterHotKey`** — atalhos hoje só funcionam com a janela focada.
- **`stats.perdidos`** — o libobs não reporta descarte por fonte na API pública.
- **~1 s de preto na troca de cena** — o WGC reaquece.
