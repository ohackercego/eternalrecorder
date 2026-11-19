"""Conserta o container/codec do arquivo depois que a gravação termina.

## Por que existe

O muxer do libobs (`ffmpeg_muxer`) grava bem container de vídeo — mp4, mkv,
mov, flv — mas para áudio puro ele não produz mp3/wav/flac: pedir `format:
"mp3"` gera arquivo de 0 bytes (medido). O motor então grava num `.mkv`
temporário e chama este módulo no `parar()` para entregar o formato pedido.

Além disso, se o usuário escolhe `.wav` mas o codec de áudio do libobs é AAC,
o arquivo seria um WAV que nenhum editor abre direito. Aqui o codec é
recodificado para o que a extensão promete.

## Regra

- MP4/MKV/MOV/FLV: já está certo, não toca (cópia de pacotes só se preciso).
- MP3/WAV/FLAC/M4A: extrai só o áudio e recodifica no codec da extensão.

Nunca levanta: se falhar, o arquivo original fica intacto. Melhor um arquivo
com container "errado" do que arquivo nenhum.
"""
from __future__ import annotations

from pathlib import Path

import av
import numpy as np

# codec de áudio por extensão
CODEC_AUDIO = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "flac": "flac",
    "m4a": "aac",
    "aac": "aac",
    "ogg": "libvorbis",
}
# container de destino por extensão
CONTAINER = {
    "mp3": "mp3", "wav": "wav", "flac": "flac", "m4a": "ipod",
    "mp4": "mp4", "mkv": "matroska", "webm": "webm", "mov": "mov",
    "ogg": "ogg",
}
FORMATOS_AUDIO_PUROS = set(CODEC_AUDIO)


def precisa_consertar(caminho: str) -> bool:
    """O container no disco difere da extensão pedida?"""
    try:
        ext = Path(caminho).suffix.lstrip(".").lower()
        esperado = CONTAINER.get(ext)
        if esperado is None:
            return False
        with av.open(caminho) as c:
            atual = (c.format.name or "").lower()
    except Exception:
        return False
    grupos = {
        "mp3": {"mp3"}, "wav": {"wav"}, "flac": {"flac"},
        "ipod": {"ipod", "mp4", "mov"}, "mp4": {"mp4", "mov"},
        "mov": {"mov", "mp4"}, "matroska": {"matroska", "webm"},
        "webm": {"webm", "matroska"},
    }
    return esperado not in grupos.get(atual, {atual})


def _extrair_audio(origem: str, destino: str, codec: str) -> None:
    """Recodifica as trilhas de áudio no codec/container pedido."""
    ext = Path(destino).suffix.lstrip(".").lower()
    container_fmt = CONTAINER.get(ext, ext)

    with av.open(origem) as entrada:
        if not entrada.streams.audio:
            raise RuntimeError("arquivo sem trilha de áudio")
        # sample_rate pode vir None no codec_context (acontece com AAC vindo
        # de Matroska): lê do primeiro quadro decodificado nesse caso.
        taxas = set()
        for s in entrada.streams.audio:
            taxa_s = s.codec_context.sample_rate
            if not taxa_s:
                taxa_s = getattr(s, "rate", None)
            if taxa_s:
                taxas.add(int(taxa_s))
        if not taxas:
            taxas = {48000}
        taxa = 48000 if 48000 in taxas else sorted(taxas)[0]

        with av.open(destino, "w", format=container_fmt) as saida:
            out = saida.add_stream(codec, rate=taxa)
            # PCM (wav) não tem bitrate: atribuir None estoura no setter
            if codec != "pcm_s16le":
                out.bit_rate = 192000
            else:
                out.layout = "stereo"

            # ── MISTURA as trilhas, não concatena ──
            # BUG que isto corrige: o comentário dizia "soma as trilhas" mas o
            # código fazia np.concatenate. Com mic + sistema (duas trilhas de
            # 6 s) o WAV saía com 12 s: 6 s do microfone seguidos de 6 s do
            # sistema — o usuário ouvia a própria fala repetida e travando.
            # Medido: 6,037 s de origem viravam 12,028 s de destino.
            #
            # Agora cada trilha é decodificada em separado, alinhada pelo
            # início, somada amostra por amostra e limitada em int16.
            trilhas: list[np.ndarray] = []
            ressampler = av.AudioResampler(format="s16", layout="stereo",
                                           rate=taxa)

            for stream in entrada.streams.audio:
                pedacos: list[np.ndarray] = []
                for quadro in entrada.decode(stream):
                    for fr in ressampler.resample(quadro):
                        arr = fr.to_ndarray()
                        # ── FORMATO DO to_ndarray() ──
                        # Para s16 ESTÉREO o PyAV devolve (1, amostras*2) —
                        # os dois canais INTERCALADOS numa linha só — e não
                        # (canais, amostras) como eu supunha. O `.T` ingênuo
                        # virava (amostras*2, 1), e o from_ndarray() depois
                        # lia o buffer como "1 canal × 96000 amostras": o
                        # arquivo saía com o DOBRO da duração (5 s viravam
                        # 9,98 s) — era a fala repetida que o usuário ouviu.
                        if arr.ndim == 2 and arr.shape[0] == 1:
                            plano = arr.reshape(-1)
                            if plano.size % 2:
                                plano = plano[:-1]
                            inter = plano.reshape(-1, 2)      # (amostras, 2)
                        elif arr.ndim == 2 and arr.shape[0] == 2:
                            inter = arr.T                     # (amostras, 2)
                        else:
                            mono = arr.reshape(-1)
                            inter = np.stack([mono, mono], axis=1)
                        pedacos.append(inter.astype(np.int32))
                if pedacos:
                    trilhas.append(np.concatenate(pedacos, axis=0))

            if not trilhas:
                raise RuntimeError("nenhuma amostra de áudio decodificada")

            # soma com padding: a trilha mais curta é completada com silêncio
            maior = max(t.shape[0] for t in trilhas)
            acumulado = np.zeros((maior, 2), dtype=np.int32)
            for t in trilhas:
                acumulado[:t.shape[0]] += t
            # satura para não estourar o int16 (clip, não wrap)
            acumulado = np.clip(acumulado, -32768, 32767).astype(np.int16)

            # envia em blocos de 1 s para não estourar memória
            #
            # ── O RESHAPE QUE DOBRAVA A DURAÇÃO ──
            # `acumulado` é (amostras, 2) — intercalado, LRLRLR.
            # Para `s16` o PyAV exige **packed**: array.shape[0] tem que ser 1
            # (senão levanta "Expected packed array.shape[0] to equal 1").
            # E o valor de shape[1] é o TOTAL DE AMOSTRAS DO BUFFER, não o
            # número de frames — ou seja 2*N. Com isso o frame sai com
            # `samples == N`, que é o correto.
            #
            # Medido: 5 s de microfone viravam 9,984 s no WAV. Era o efeito
            # que o usuário descreveu como "repetindo: oi galera, galera".
            # O MP3 escapava porque o codec delimita pelo header; o WAV (PCM)
            # entregava o buffer cru e o player tocava tudo.
            passo = taxa
            for i in range(0, acumulado.shape[0], passo):
                bloco = acumulado[i:i + passo]
                # (frames, canais) -> buffer empacotado com shape (1, N*canais)
                fr = av.AudioFrame.from_ndarray(
                    bloco.reshape(1, -1), format="s16", layout="stereo")
                fr.sample_rate = taxa
                fr.pts = i
                fr.time_base = __import__("fractions").Fraction(1, taxa)
                for pac in out.encode(fr):
                    saida.mux(pac)
            for pac in out.encode():
                saida.mux(pac)


def _copiar_av(origem: str, destino: str) -> None:
    """Copia vídeo e áudio sem reencodar (destino com vídeo)."""
    ext = Path(destino).suffix.lstrip(".").lower()
    container_fmt = CONTAINER.get(ext, None)
    with av.open(origem) as entrada:
        saida = av.open(destino, "w", format=container_fmt)
        mapa = {}
        for st in entrada.streams:
            if st.type not in ("video", "audio"):
                continue
            mapa[st.index] = saida.add_stream_from_template(st)
        for pacote in entrada.demux():
            if pacote.dts is None:
                continue
            alvo = mapa.get(pacote.stream.index)
            if alvo is None:
                continue
            pacote.stream = alvo
            saida.mux(pacote)
        saida.close()


def consertar(caminho: str) -> dict:
    """Reescreve o arquivo no container/codec que a extensão promete.

    Devolve {"consertado": bool, "motivo": str}. Nunca levanta: se falhar, o
    arquivo original fica intacto (melhor arquivo "errado" que arquivo nenhum).
    """
    try:
        if not Path(caminho).exists() or Path(caminho).stat().st_size < 1024:
            return {"consertado": False, "motivo": "arquivo pequeno/ausente"}
        ext = Path(caminho).suffix.lstrip(".").lower()
        if ext not in CONTAINER:
            return {"consertado": False, "motivo": f"extensão {ext} sem regra"}

        if not precisa_consertar(caminho):
            return {"consertado": False, "motivo": "já está no formato certo"}

        # se o codec final é o mesmo e só o container muda, copiar basta.
        # mp3/wav/flac exigem codec próprio: recodifica.
        parcial = caminho + ".tmp." + ext
        Path(parcial).unlink(missing_ok=True)
        try:
            if ext in FORMATOS_AUDIO_PUROS:
                _extrair_audio(caminho, parcial, CODEC_AUDIO[ext])
            else:
                _copiar_av(caminho, parcial)
            if not Path(parcial).exists() or Path(parcial).stat().st_size < 512:
                raise RuntimeError("saída vazia")
            Path(caminho).unlink()
            Path(parcial).rename(caminho)
            return {"consertado": True, "motivo": f"convertido para {ext}"}
        finally:
            Path(parcial).unlink(missing_ok=True)
    except Exception as e:
        return {"consertado": False,
                "motivo": f"{type(e).__name__}: {e}"}
