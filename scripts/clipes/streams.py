"""Lives agora: quem está transmitindo GTA 6 na Twitch, no YouTube e na Kick, por espectadores.

  python streams.py [--query "gta 6"] [--limit 20]

Salva cortes/_lives.json. Twitch sem conta/chave (GQL público da web), YouTube pelo yt-dlp, Kick uma tentativa.
Os números de espectadores são exatamente os que a plataforma devolveu na hora.
(adaptado do gtavi-claudecode, licença MIT)
"""
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, run, save_json, ytdlp_base, ytdlp_json

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass


def youtube(query, limit):
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgJAAQ%253D%253D"
    r = run(ytdlp_base() + ["--flat-playlist", "-J", "--playlist-end", str(limit), url], capture=True, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"aviso: busca no YouTube falhou: {(r.stderr or '')[-300:]}", flush=True)
        return []
    ids = [e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
           for e in json.loads(r.stdout).get("entries") or [] if e and e.get("id")]

    def one(u):
        try:
            return ytdlp_json(u, ["--skip-download"])
        except BaseException:
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = list(ex.map(one, ids))
    out = []
    for i in infos:
        if not i or not i.get("is_live"):
            continue
        out.append({"plataforma": "YouTube", "canal": i.get("channel") or i.get("uploader") or "",
                    "titulo": i.get("title") or "", "url": i.get("webpage_url") or "",
                    "espectadores": i.get("concurrent_view_count"),
                    "inicio": i.get("release_timestamp") or i.get("timestamp"),
                    "miniatura": i.get("thumbnail") or ""})
    return out


def twitch(limit):
    import twitch as tw
    try:
        rows = tw.top_streams("Grand Theft Auto VI", limit)
    except Exception as e:
        print(f"aviso: Twitch falhou: {e}", flush=True)
        return []
    return [{"plataforma": "Twitch", "canal": r["name"], "titulo": r["title"], "url": r["url"], "espectadores": r["viewers"],
             "inicio": tw.started_ts(r["created_at"]), "miniatura": r.get("preview") or ""} for r in rows]


def kick(query):
    try:
        import requests
        r = requests.get("https://kick.com/api/v2/channels", params={"query": query}, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        return [{"plataforma": "Kick", "canal": c.get("slug", ""), "titulo": (c.get("livestream") or {}).get("session_title", ""),
                 "url": f"https://kick.com/{c.get('slug', '')}", "espectadores": (c.get("livestream") or {}).get("viewer_count"),
                 "inicio": None, "miniatura": ""} for c in items if isinstance(c, dict) and c.get("livestream")]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="gta 6"); ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    print("(1/3) Twitch (categoria Grand Theft Auto VI)…", flush=True)
    tw = twitch(a.limit)
    print(f"   {len(tw)} lives", flush=True)
    print("(2/3) YouTube (lives ao vivo agora)…", flush=True)
    yt = youtube(a.query, a.limit)
    print(f"   {len(yt)} lives", flush=True)
    print("(3/3) Kick…", flush=True)
    kk = kick(a.query)
    print(f"   {len(kk)} lives", flush=True)
    itens = sorted(tw + yt + kk, key=lambda r: r["espectadores"] or -1, reverse=True)
    save_json(ROOT / "_lives.json", {"atualizado": time.time(), "consulta": a.query, "itens": itens})
    for r in itens[:10]:
        print(f"{r['plataforma']:8} {str(r['espectadores'] or ''):>7}  {r['canal'][:24]:24} {r['titulo'][:50]}", flush=True)
    print(f"pronto: {len(itens)} lives", flush=True)


if __name__ == "__main__":
    main()
