"""Busca rápida de momentos somando sinais do vídeo e fala de regiões prioritárias.

Uso: python momentos_prioritarios.py <link-ou-arquivo> --top 10 --min 45 --max 60 --max-minutes 45
"""
import argparse
import math
from pathlib import Path
import wave

import numpy as np
import moments as base


def salvar(arquivo, dados):
    temporario = arquivo.with_suffix(".novo")
    base.save_json(temporario, dados)
    temporario.replace(arquivo)


def selecionar_janelas(score, maximo, top):
    largura = min(len(score), max(30, math.ceil(maximo) + 12))
    if not largura:
        return []
    cobertos = np.zeros(len(score), dtype=bool)
    janelas = []
    for pico in np.argsort(-score, kind="stable"):
        if cobertos[pico]:
            continue
        inicio = max(0, min(len(score) - largura, int(pico) - largura // 3))
        fim = inicio + largura
        if cobertos[inicio:fim].any():
            continue
        janelas.append((inicio, fim))
        cobertos[inicio:fim] = True
        if len(janelas) >= top + 2:
            break
    return sorted(janelas)


def transcrever_janelas(wav, pasta, janelas):
    saida, alcance = pasta / "transcript.json", pasta / "transcript_alcance.json"
    info = base.load_json(alcance) if alcance.exists() else {}
    denso = float(info.get("segundos", 0))
    antigas = base.load_json(saida) if saida.exists() else []
    cache = pasta / "transcricoes_prioritarias"
    cache.mkdir(exist_ok=True)
    modelo, idioma = None, info.get("idioma")

    carregar = base.carregar_whisper      # todos os núcleos do processador

    def extrair(modelo, amostras, inicio, idioma):
        segs, meta = modelo.transcribe(amostras, language=idioma, word_timestamps=True, vad_filter=True,
                                       beam_size=1, best_of=1, temperature=0.0)
        return [{"w": w.word.strip(), "s": round(inicio + w.start, 2), "e": round(inicio + w.end, 2)}
                for seg in segs for w in (seg.words or [])], meta.language

    try:
        import ctranslate2
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    except Exception:
        device = "cpu"
    import nuvem
    faltando = [(ini, fim) for ini, fim in janelas if denso < fim and not (cache / f"{ini}-{fim}.json").exists()]
    pela_nuvem = False
    if faltando and nuvem.configurada():
        print(f"   transcrevendo {len(faltando)} regiões na nuvem ({nuvem.provedor()}), várias ao mesmo tempo…", flush=True)
        try:
            todas, idioma_nuvem = nuvem.transcrever(wav, faltando, progresso=lambda f, t: print(
                f"transcrição prioritária: {round(len(janelas) - len(faltando) + len(faltando) * f / t)}/{len(janelas)}", flush=True))
            idioma = idioma or idioma_nuvem
            for ini, fim in faltando:
                salvar(cache / f"{ini}-{fim}.json", {"palavras": [w for w in todas if ini <= w["s"] < fim], "idioma": idioma})
            pela_nuvem = True
        except Exception as e:
            print(f"   a transcrição na nuvem falhou ({str(e)[:160]}); usando o Whisper do PC", flush=True)
    palavras = []
    with wave.open(str(wav)) as audio:
        for i, (ini, fim) in enumerate(janelas, 1):
            arq = cache / f"{ini}-{fim}.json"
            if denso >= fim:
                novas = [w for w in antigas if ini <= w["s"] < fim]
            elif arq.exists():
                salvo = base.load_json(arq)
                novas = salvo["palavras"]
                idioma = idioma or salvo.get("idioma")
            else:
                audio.setpos(min(audio.getnframes(), ini * 16000))
                amostras = np.frombuffer(audio.readframes((fim - ini) * 16000), dtype="<i2").astype(np.float32) / 32768
                novas = []
                if len(amostras):
                    try:
                        if modelo is None:
                            modelo = carregar(device)
                        novas, idioma = extrair(modelo, amostras, ini, idioma)
                    except RuntimeError:
                        if device != "cuda":
                            raise
                        device = "cpu"
                        modelo = carregar(device)
                        novas, idioma = extrair(modelo, amostras, ini, idioma)
                salvar(arq, {"palavras": novas, "idioma": idioma})
            palavras.extend(w for w in novas if ini <= w["s"] < fim)
            if not pela_nuvem:          # a nuvem já mostrou o avanço
                print(f"transcrição prioritária: {i}/{len(janelas)}", flush=True)
    conservadas = [w for w in antigas if w["s"] < denso or not any(a <= w["s"] < b for a, b in janelas)]
    novas = [w for w in palavras if w["s"] >= denso]
    salvar(alcance, {"segundos": denso, "idioma": idioma})
    salvar(saida, sorted(conservadas + novas, key=lambda w: w["s"]))
    return palavras


def localizar(score, partes, words, heat, janelas, dur, minimo, maximo):
    """Escolhe um pico por região para garantir que o corte tenha áudio transcrito."""
    usados = np.zeros(len(score), dtype=bool)
    por_segundo = {t: (ini, fim) for ini, fim in janelas for t in range(ini, fim)}
    picks = []
    for pico in np.argsort(-score):
        if score[pico] <= 0:
            break
        if pico not in por_segundo or usados[pico]:
            continue
        a, b = por_segundo[pico]
        ini, fim = base.limites(int(pico), score, words, dur, minimo, maximo)
        ini, fim = max(ini, a), min(fim, b)
        if fim - ini < minimo:
            ini = max(a, min(ini, b - minimo))
            fim = min(b, ini + minimo)
        if fim <= ini:
            continue
        usados[a:b] = True
        motivos = []
        if partes["volume"][pico] > 1:
            motivos.append("pico de volume")
        if partes["empolgacao"][pico] > 0:
            motivos.append("fala empolgada")
        if partes["risada"][pico] > 0:
            motivos.append("risada")
        if heat[pico] > 0.5:
            motivos.append("mais repetido")
        if partes["chat"][pico] > 1:
            motivos.append("pico no chat")
        texto = " ".join(w["w"] for w in words if ini <= w["s"] < fim)
        picks.append({"n": len(picks) + 1, "start": ini, "end": fim, "peak": int(pico),
                      "score": round(float(score[pico]), 2), "why": motivos or ["energia geral"], "text": texto[:400]})
    return picks


def abrir_fonte(src, pasta, minutos, info_de):
    """Evita consultar o YouTube outra vez quando a fonte já cobre o intervalo."""
    arquivo = pasta / "info.json"
    video = pasta / "source.mp4"
    if base.is_url(src) and video.is_file() and arquivo.is_file():
        info = base.load_json(arquivo)
        duracao = info.get("duration") or 0
        chat_pronto = not info.get("was_live") or any(pasta.glob("chat*.live_chat.json"))
        if duracao and chat_pronto and float(base.ffprobe(video)["format"]["duration"]) + 3 >= min(duracao, minutos * 60):
            print("   vídeo e dados já baixados; reaproveitando a fonte", flush=True)
            return video, info
    return base.fetch(src, pasta, minutos, info_de)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--min", type=float, default=15)
    ap.add_argument("--max", type=float, default=40)
    ap.add_argument("--max-minutes", type=int, default=45)
    ap.add_argument("--info-de")
    ap.add_argument("--sem-ia", action="store_true")
    a = ap.parse_args()
    pasta = base.job_dir(a.src)
    tempos = base.TemposAnalise()
    print("(1/4) baixando ou reabrindo o vídeo…", flush=True)
    video, info = abrir_fonte(a.src, pasta, a.max_minutes, a.info_de)
    fonte = base.fonte_de_audio(video)      # o áudio já baixado, enquanto o vídeo em 1080p vem em segundo plano
    dur = min(float(base.ffprobe(fonte)["format"]["duration"]), a.max_minutes * 60)
    tempos.registrar("fonte")
    print("(2/4) analisando o volume…", flush=True)
    wav, db = base.audio_rms(fonte, pasta, dur)
    n = len(db)
    if not n:
        raise SystemExit("vídeo sem áudio suficiente para analisar")
    heat = np.zeros(n)
    for trecho in info.get("heatmap") or []:
        heat[int(trecho["start_time"]):math.ceil(trecho["end_time"])] = trecho["value"]
    chat = base.chat_series(pasta, n, None, info)
    sinais, _, _ = base.sinais(db, [], heat, chat, n)
    janelas = selecionar_janelas(sinais, a.max, a.top)
    segundos = sum(b - a for a, b in janelas)
    tempos.registrar("audio")
    print(f"(3/4) transcrevendo {len(janelas)} regiões prioritárias ({segundos // 60} min {segundos % 60:02d} s)…", flush=True)
    words = transcrever_janelas(wav, pasta, janelas)
    tempos.registrar("fala")
    print("(4/4) pontuando os momentos…", flush=True)
    score, partes, pesos = base.sinais(db, words, heat, chat, n)
    picks = localizar(score, partes, words, heat, janelas, dur, a.min, a.max)
    meta = base.load_json(pasta / "info.json")
    com_ia = bool(picks) and not a.sem_ia and base.revisar_com_ia(picks, meta, a.top)
    if not com_ia:
        melhor = max((p["score"] for p in picks), default=1) or 1
        for p in picks:
            p["nota"] = round(10 * max(0, p["score"]) / melhor, 1)
    picks = sorted(picks, key=lambda p: (-p.get("nota", 0), p["start"]))[:a.top]
    if not picks:
        raise SystemExit("nenhum momento forte encontrado nas regiões analisadas")
    tempos.registrar("selecao")
    base.esperar_video()
    tempos.registrar("espera")
    base.numerar_momentos(picks, pasta)
    salvar(pasta / "candidates.json", {"source": str(video), "info": meta, "duration": dur, "tempos": tempos.etapas, "candidates": picks,
           "signals": {"heatmap": bool(pesos["mais_repetido"]), "chat": bool(pesos["chat"]), "words": len(words),
                       "ia": com_ia, "pesos": pesos, "prioritaria": True, "segundos_transcritos": segundos}})
    relatorio = [f"# Momentos: {meta.get('title', '')}", f"Fonte: {meta.get('webpage_url', '')}", ""]
    for p in picks:
        relatorio += [f"## {p['n']}. {p['start']:.2f}–{p['end']:.2f} s · nota {p['nota']}", p["text"], ""]
    (pasta / "candidates.md").write_text("\n".join(relatorio), encoding="utf-8")
    print(f"pronto: {len(picks)} momentos em {pasta.name}", flush=True)


if __name__ == "__main__":
    main()
