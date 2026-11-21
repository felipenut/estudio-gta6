"""Tendências do YouTube: os vídeos de GTA 6 mais vistos (semana ou mês) para virar tema.

  python tendencias.py [--periodo relevancia|subindo|hoje|semana|mes] [--n 25]

"subindo": os enviados nas últimas 48 h, ordenados por VIEWS POR HORA (o que está crescendo agora, mesmo de canal pequeno).

Salva videos/_tendencias.json. Usa o yt-dlp (o mesmo da biblioteca); não baixa nada, só lista.
"""
import argparse, datetime, json, re, subprocess, sys
from pathlib import Path
from urllib.parse import quote_plus

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from baixar import ytdlp  # noqa: E402

RAIZ = AQUI.parent.parent
SAIDA = RAIZ / "videos" / "_tendencias.json"
CONSULTAS = ["gta 6", "gta 6 shorts"]
# filtro "sp" do YouTube. "relevancia" = a busca normal (a mesma ordem que você vê no YouTube)
SP = {"relevancia": "", "subindo": "CAI%3D", "hoje": "CAMSBAgCEAE%3D", "semana": "CAMSBAgDEAE%3D", "mes": "CAMSBAgEEAE%3D"}
JANELA_SUBINDO_H = 48
SOBRE_GTA6 = re.compile(r"\bgta\s*(6|vi)\b|gta6|gtavi\b|grand theft auto (6|vi)\b|\bleonida\b|\bvice city\b|\blucia\b", re.I)
LIVE = re.compile(r"\b(live|ao vivo|livestream|stream)\b|🔴", re.I)
MAX_DURACAO = 60 * 60   # vídeos de explicação de 20–40 min são ótimas fontes de tema; corta só lives/maratonas


def util(e):
    """Só o que dá para virar tema: fala de GTA 6, não é live, não é vídeo de horas."""
    t = e.get("title") or ""
    if not SOBRE_GTA6.search(t):
        return False
    if e.get("live_status") in ("is_live", "was_live", "is_upcoming") or LIVE.search(t):
        return False
    d = e.get("duration")
    return not (d and d > MAX_DURACAO)


def buscar(consulta, periodo, n):
    url = f"https://www.youtube.com/results?search_query={quote_plus(consulta)}" + (f"&sp={SP[periodo]}" if SP[periodo] else "")
    r = subprocess.run(ytdlp() + [url, "--flat-playlist", "-J", "--playlist-end", str(n)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(f"  aviso: falhou '{consulta}': {r.stderr.strip()[-300:]}")
        return []
    return [e for e in json.loads(r.stdout).get("entries", []) if e]


def detalhes(url):
    r = subprocess.run(ytdlp() + ["-J", "--skip-download", url], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def views_por_hora(itens):
    """Busca a data de envio de cada vídeo e calcula views/hora (mesma conta do trend-radar)."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    print(f"   lendo a data de envio de {len(itens)} vídeos (views por hora)…", flush=True)
    with ThreadPoolExecutor(6) as ex:
        infos = list(ex.map(lambda x: detalhes(x["url"]), itens))
    agora, bons = time.time(), []
    for x, i in zip(itens, infos):
        t = i and (i.get("timestamp") or i.get("release_timestamp"))
        if not t or i.get("is_live"):
            continue
        idade = max(0.25, (agora - t) / 3600)
        if idade > JANELA_SUBINDO_H:
            continue
        x["views"] = i.get("view_count") or x["views"]
        x["idade_h"] = round(idade, 1)
        x["vph"] = round(x["views"] / idade)
        x["mais_repetido"] = bool(i.get("heatmap"))
        bons.append(x)
    return sorted(bons, key=lambda x: -x["vph"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", choices=list(SP), default="relevancia")
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    vistos = {}
    for i, c in enumerate(CONSULTAS, 1):
        print(f"({i}/{len(CONSULTAS)}) buscando '{c}' ({a.periodo})...", flush=True)
        achados = buscar(c, a.periodo, a.n)
        bons = [e for e in achados if util(e)]
        print(f"   {len(achados)} resultados, {len(bons)} úteis (GTA 6, sem live, até 1 h)", flush=True)
        for e in bons:
            vid = e.get("id")
            if not vid or vid in vistos:
                continue
            dur = e.get("duration") or 0
            vistos[vid] = {"id": vid, "titulo": e.get("title") or "", "canal": e.get("channel") or e.get("uploader") or "",
                           "views": e.get("view_count") or 0, "duracao": dur, "short": bool(dur and dur <= 180),
                           "url": f"https://www.youtube.com/watch?v={vid}", "consulta": c, "ordem": len(vistos)}
    itens = list(vistos.values())
    if a.periodo == "subindo":
        itens = views_por_hora(itens[:40])
    elif a.periodo != "relevancia":            # nos modos "mais vistos", ordena por views; na relevância, mantém a ordem do YouTube
        itens.sort(key=lambda x: -x["views"])
    itens = itens[:60]
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"atualizado": datetime.datetime.now().isoformat(timespec="minutes"),
                                 "periodo": a.periodo, "itens": itens}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(itens)} vídeos salvos. Top 5:")
    for x in itens[:5]:
        extra = f"  {x['vph']:,}/h" if x.get("vph") else ""
        print(f"  {x['views']:>12,}{extra}  {x['titulo'][:80]}  ({x['canal']})")
    return 0 if itens else 1


if __name__ == "__main__":
    sys.exit(main())
