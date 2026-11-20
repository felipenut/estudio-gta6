"""Um clipe, vários idiomas: legenda palavra por palavra e gancho/título traduzidos, mesmo layout do corte.

  python traduzir.py <pasta do corte> --pick <n> --langs en,es [--voz]

Gera edits/clip_<n>_<idioma>.mp4 e edits/clip_<n>_legendas.json (texto do post por idioma).
A tradução usa a IA configurada no Estúdio (chave NVIDIA). --voz põe uma voz neural pronta (edge-tts, nunca imita
o streamer) lendo só o gancho traduzido nos primeiros 2,5 s, com o áudio original mais baixo por baixo.
(adaptado do multilang do gtavi-claudecode, licença MIT)
"""
import argparse, asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent))
from common import ffprobe, load_json, run, save_json, tool
from cut import CAP_Y, build_ass, titulo_e_faixa, video_filter

IDIOMAS = {"pt": "português do Brasil", "en": "inglês (EUA)", "es": "espanhol (América Latina)", "de": "alemão",
           "ru": "russo", "fr": "francês", "it": "italiano"}
VOZES = {"pt": "pt-BR-AntonioNeural", "en": "en-US-GuyNeural", "es": "es-MX-JorgeNeural", "de": "de-DE-ConradNeural",
         "ru": "ru-RU-DmitryNeural", "fr": "fr-FR-HenriNeural", "it": "it-IT-DiegoNeural"}
HASHTAGS = {"pt": "#GTA6 #GTAVI #gta #games", "en": "#GTA6 #GTAVI #gaming #gta", "es": "#GTA6 #GTAVI #gaming #gta"}
HOOK_SECONDS = 2.5


def sentences(words):
    out, cur = [], []
    for w in words:
        if cur and w["s"] - cur[-1]["e"] > 0.8:
            out.append(cur); cur = []
        cur.append(w)
        if w["w"][-1:] in ".?!":
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def traduzir_lote(lang, frases, gancho, titulo):
    """Uma chamada à IA por idioma: devolve (frases, gancho, titulo) traduzidos."""
    import ia
    pedido = {"gancho": gancho, "titulo": titulo, "frases": frases}
    msgs = [{"role": "system", "content": "Você é tradutor de legendas de vídeos curtos de games. Traduza de forma natural e "
                                          "curta, como um criador nativo falaria. Não acrescente fatos, números, nomes ou datas. "
                                          "Mantenha 'GTA 6', nomes de pessoas, canais e lugares do jogo como estão. Se o texto "
                                          "já estiver no idioma pedido, apenas corrija a pontuação."},
            {"role": "user", "content": f"Traduza para {IDIOMAS.get(lang, lang)}. Devolva SOMENTE JSON no formato "
                                        '{"gancho": "...", "titulo": "...", "frases": ["...", ...]} com exatamente '
                                        f"{len(frases)} frases, na mesma ordem. Campos vazios continuam vazios.\n\n"
                                        + __import__("json").dumps(pedido, ensure_ascii=False)}]
    r = ia.chat_json(msgs, temperatura=0.2, max_tokens=4000)
    novas = [str(x) for x in (r.get("frases") or [])]
    if len(novas) != len(frases):
        print(f"aviso: a IA devolveu {len(novas)} frases em vez de {len(frases)}; completando com o original", flush=True)
        novas = (novas + frases[len(novas):])[:len(frases)]
    return novas, (r.get("gancho") or "") if gancho else "", (r.get("titulo") or "") if titulo else ""


def espalhar(sents, traduzidas):
    """Distribui as palavras traduzidas no tempo de cada frase original."""
    res = []
    for sent, txt in zip(sents, traduzidas):
        new = txt.split()
        if not new:
            continue
        a, b = sent[0]["s"], sent[-1]["e"]
        step = (b - a) / len(new)
        res += [{"w": x, "s": a + i * step, "e": a + (i + 1) * step} for i, x in enumerate(new)]
    return res


def fazer_voz(lang, texto, dest):
    import edge_tts
    voz = VOZES.get(lang)
    if not voz:
        return None
    asyncio.run(edge_tts.Communicate(texto, voz).save(str(dest)))
    return dest


def render(src, s0, e0, rp, ass, band, mp4, voz_mp3=None):
    v = video_filter(rp["layout"], rp["cam"], ass, band=band, cam_side=rp.get("side") or "right",
                     src=tuple(rp["src"]) if rp.get("src") else None, game_x=rp.get("gx"),
                     face_expr=tuple(rp["face_expr"]) if rp.get("face_expr") else None)
    cmd = [tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{e0:.2f}", "-i", src]
    if voz_mp3:
        dur = float(ffprobe(voz_mp3)["format"]["duration"])
        tempo = f"atempo={min(2.0, dur / HOOK_SECONDS):.3f}," if dur > HOOK_SECONDS else ""
        cmd += ["-i", str(voz_mp3)]
        a = (f"[0:a]volume=0.2:enable='lt(t,{HOOK_SECONDS})'[bed];"
             f"[1:a]{tempo}atrim=0:{HOOK_SECONDS},afade=t=out:st={HOOK_SECONDS - 0.15}:d=0.15,apad[tts];"
             f"[bed][tts]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[ao]")
        cmd += ["-filter_complex", v + ";" + a, "-map", "[vo]", "-map", "[ao]"]
    else:
        cmd += ["-filter_complex", v, "-map", "[vo]", "-map", "0:a?", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-movflags", "+faststart", str(mp4)]
    run(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--langs", default="en,es"); ap.add_argument("--voz", action="store_true")
    a = ap.parse_args()
    d = Path(a.job); out = d / "edits"
    side = out / f"clip_{a.pick}.json"
    if not side.exists():
        sys.exit(f"corte {a.pick} ainda não existe: corte o clipe primeiro.")
    meta = load_json(side)
    rp = meta.get("render") or {"layout": meta.get("layout", "blur"), "cam": meta.get("cam", "auto")}
    if rp.get("cam") == "auto" and rp["layout"] in ("react", "facecam"):
        rp["layout"] = "blur"
    src = load_json(d / "candidates.json")["source"]
    s0, e0 = meta["start"], meta["end"]
    hook = "" if meta.get("title") else (meta.get("hook") or "")
    title = meta.get("title") or ""
    words = [w for w in load_json(d / "transcript.json") if s0 <= w["s"] < e0 and w["w"]]
    sents = sentences(words)
    frases = [" ".join(w["w"] for w in s) for s in sents]
    langs = [x.strip() for x in a.langs.split(",") if x.strip()]
    legendas = load_json(out / f"clip_{a.pick}_legendas.json") if (out / f"clip_{a.pick}_legendas.json").exists() else {}
    canal = meta.get("source_channel") or ""
    for k, lang in enumerate(langs, 1):
        print(f"({k}/{len(langs)}) {IDIOMAS.get(lang, lang)}: traduzindo com a IA…", flush=True)
        trad, h, t = traduzir_lote(lang, frases, hook, title)
        tw = espalhar(sents, trad) if rp.get("captions", "word") != "none" else []
        titulo, band = titulo_e_faixa(t, rp.get("title_style", "box"), rp.get("title_secs", 0), rp["layout"])
        ass = out / f"clip_{a.pick}_{lang}.ass"
        ass.write_text(build_ass(tw, s0, e0, h, CAP_Y[rp["layout"]], title=titulo, caps=rp.get("captions", "word"),
                                 profanity=rp.get("profanity", False)), encoding="utf-8")
        mp4 = out / f"clip_{a.pick}_{lang}.mp4"
        mp3 = None
        if a.voz and (h or t):
            mp3 = fazer_voz(lang, h or t, Path(tempfile.gettempdir()) / f"clip_{a.pick}_{lang}_gancho.mp3")
        print(f"   renderizando {mp4.name}…", flush=True)
        render(src, s0, e0, rp, ass, band, mp4, mp3)
        cred = {"pt": "🎥 via", "en": "🎥 via", "es": "🎥 vía"}.get(lang, "🎥 via")
        legendas[lang] = "\n".join(x for x in [h or t, f"{cred} @{canal}" if canal else "", HASHTAGS.get(lang, "#GTA6 #GTAVI")] if x)
        save_json(out / f"clip_{a.pick}_legendas.json", legendas)
        print(f"ok: {mp4}", flush=True)


if __name__ == "__main__":
    main()
