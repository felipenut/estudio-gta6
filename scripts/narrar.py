"""Gera a narração do roteiro e os tempos de cada palavra (para legenda e cortes).

Uso:
  python narrar.py roteiro.json --saida out/            # voz neural grátis (edge-tts)
  python narrar.py roteiro.json --saida out/ --audio minha_voz.mp3   # voz própria/ElevenLabs + transcrição local (faster-whisper)
  python narrar.py roteiro.json --saida out/ --audio voz.mp3 --palavras palavras_externas.json
       (palavras_externas: lista [{"word"|"text"|"palavra", "start"|"inicio", "end"|"fim"}], ex.: transcrição da ElevenLabs)

Saídas: <saida>/narracao.mp3 e <saida>/palavras.json  ([{palavra, inicio, fim}] em segundos)
Vozes pt-BR boas: pt-BR-AntonioNeural (masc.), pt-BR-FranciscaNeural (fem.), pt-BR-ThalitaMultilingualNeural.
"""
import argparse, asyncio, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ler_json, salvar_json, rodar, ffmpeg_bin


def texto_do_roteiro(rot):
    return " ".join(s["texto"].strip() for s in rot["segmentos"])


async def edge(texto, voz, taxa, tom, mp3):
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=taxa, pitch=tom, boundary="WordBoundary")
    palavras = []
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palavras.append({"palavra": ch["text"], "inicio": round(ini, 3),
                                 "fim": round(ini + ch["duration"] / 1e7, 3)})
    return palavras


def whisper(audio, modelo):
    from faster_whisper import WhisperModel
    m = WhisperModel(modelo, compute_type="int8")
    segs, _ = m.transcribe(str(audio), language="pt", word_timestamps=True)
    return [{"palavra": w.word.strip(), "inicio": round(w.start, 3), "fim": round(w.end, 3)}
            for s in segs for w in s.words]


def externas(p):
    out = []
    for w in ler_json(p):
        if w.get("type") == "spacing":
            continue
        txt = w.get("palavra") or w.get("word") or w.get("text") or ""
        if not txt.strip():
            continue
        out.append({"palavra": txt.strip(), "inicio": float(w.get("inicio", w.get("start"))),
                    "fim": float(w.get("fim", w.get("end")))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roteiro")
    ap.add_argument("--saida", default="out")
    ap.add_argument("--audio", help="áudio de narração já pronto (voz própria, ElevenLabs...)")
    ap.add_argument("--palavras", help="JSON de tempos por palavra já pronto (pula transcrição)")
    ap.add_argument("--modelo-whisper", default="small")
    ap.add_argument("--forcar", action="store_true", help="refaz a narração mesmo se o texto não mudou")
    a = ap.parse_args()

    rot = ler_json(a.roteiro)
    out = Path(a.saida); out.mkdir(parents=True, exist_ok=True)
    mp3 = out / "narracao.mp3"
    import hashlib, json as _json
    try:
        import variacao
        voz = variacao.voz(rot, Path(a.roteiro).resolve().parent, out)
    except Exception as e:
        print(f"aviso: variação de voz desligada ({e})")
        voz = rot.get("voz", "pt-BR-AntonioNeural")
    print(f"voz: {voz}")
    assinatura = hashlib.md5(_json.dumps([texto_do_roteiro(rot), voz, rot.get("velocidade"),
                                          rot.get("tom"), a.audio], ensure_ascii=False).encode()).hexdigest()
    marca = out / "narracao.assinatura"
    if not a.forcar and mp3.exists() and (out / "palavras.json").exists() and marca.exists() \
            and marca.read_text().strip() == assinatura:
        print("narração já existe para este texto: reaproveitando (use --forcar para refazer)")
        return

    if a.audio:
        src = Path(a.audio)
        if src.suffix.lower() == ".mp3":
            shutil.copy(src, mp3)
        else:
            rodar([ffmpeg_bin(), "-y", "-v", "error", "-i", str(src), "-q:a", "2", str(mp3)])
        palavras = externas(a.palavras) if a.palavras else whisper(mp3, a.modelo_whisper)
    else:
        tmp = out / "narracao.tmp.mp3"                  # só substitui a narração anterior se tudo der certo
        try:
            palavras = asyncio.run(edge(texto_do_roteiro(rot), voz, rot.get("velocidade", "+12%"),
                                        rot.get("tom", "+0Hz"), tmp))
        except Exception as e:
            tmp.unlink(missing_ok=True)
            sys.exit(f"falha na voz (sem internet ou serviço fora do ar?): {e}")
        tmp.replace(mp3)
    if not palavras:
        sys.exit("nenhuma palavra com tempo foi obtida")
    salvar_json(out / "palavras.json", palavras)
    marca.write_text(assinatura)
    print(f"ok: {mp3} | {len(palavras)} palavras | {palavras[-1]['fim']:.1f}s")


if __name__ == "__main__":
    main()
