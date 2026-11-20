"""Pesquisa e baixa vídeos de GTA no YouTube (yt-dlp) para a biblioteca.

  python baixar.py oficiais [--pasta biblioteca/videos] [--max-min 30]
        baixa todos os vídeos de "Grand Theft Auto VI" do canal oficial da Rockstar Games
        (trailers, Extended Look, trailer de lançamento...), pulando os que já estão na pasta
  python baixar.py pesquisar "gta 6 trailer 2 lucia" [--n 8]     # só lista (duração | canal | título | url)
  python baixar.py baixar <url> [--trecho 00:30-01:10] [--pasta biblioteca/videos]
  python baixar.py baixar "ytsearch1:gta 5 gameplay sem hud 4k"   # baixa o 1º resultado da busca

Baixa em até 1080p mp4. Requer: pip install "yt-dlp[default]" deno   (deno = runtime JS que o YouTube exige)
Depois rode: python biblioteca.py indexar <pasta>
"""
import argparse, json, re, shutil, subprocess, sys
from pathlib import Path

CANAL_ROCKSTAR = "https://www.youtube.com/@RockstarGames/videos"
FILTRO_OFICIAL = re.compile(r"grand theft auto vi\b|gta vi\b|gta 6", re.I)


def ytdlp():
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings"]
    if not shutil.which("deno"):
        try:
            from deno import find_deno_bin
            cmd += ["--js-runtimes", f"deno:{find_deno_bin()}"]
        except Exception:
            print("aviso: deno não encontrado (pip install deno) — o YouTube pode limitar a qualidade", file=sys.stderr)
    return cmd


def listar(alvo, n=None):
    args = [alvo, "--flat-playlist", "-J"]
    if n:
        args += ["--playlist-end", str(n)]
    r = subprocess.run(ytdlp() + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(r.stderr[-2000:])
    return [e for e in json.loads(r.stdout).get("entries", []) if e]


def pesquisar(consulta, n):
    for e in listar(f"ytsearch{n}:{consulta}"):
        d = e.get("duration") or 0
        print(f"{int(d // 60)}:{int(d % 60):02d} | {e.get('channel') or e.get('uploader')} | "
              f"{e.get('title')} | https://youtu.be/{e.get('id')}")


def baixar(alvo, pasta, trecho=None):
    Path(pasta).mkdir(parents=True, exist_ok=True)
    cmd = ytdlp() + [alvo, "-f", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
                     "--merge-output-format", "mp4", "--no-playlist", "--restrict-filenames",
                     "-o", str(Path(pasta) / "%(title).60s_[%(id)s].%(ext)s")]
    if trecho:
        if not re.match(r"^[\d:.]+-[\d:.]+$", trecho):
            sys.exit("trecho deve ser INICIO-FIM, ex.: 00:30-01:10")
        cmd += ["--download-sections", f"*{trecho}", "--force-keyframes-at-cuts"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr)
    if r.returncode and re.search(r"confirm your age|Sign in to confirm", r.stderr, re.I):
        # vídeo com restrição de idade: tenta com os cookies de login do YouTube
        cookies = Path("biblioteca/cookies.txt")
        tentativas = [["--cookies", str(cookies)]] if cookies.exists() else []
        tentativas += [["--cookies-from-browser", b] for b in ("firefox", "edge", "chrome", "brave", "opera")]
        for extra in tentativas:
            print(f"restrição de idade: tentando {' '.join(extra)}", flush=True)
            r2 = subprocess.run(cmd + extra)
            if r2.returncode == 0:
                return 0
        print("\nNão consegui passar a verificação de idade. Faça login no YouTube no Firefox e rode de novo,\n"
              "ou exporte os cookies do YouTube (extensão 'Get cookies.txt LOCALLY') para biblioteca/cookies.txt.")
    return r.returncode


def oficiais(pasta, max_min):
    Path(pasta).mkdir(parents=True, exist_ok=True)
    ja = " ".join(p.name for p in Path(pasta).iterdir())
    vids = [e for e in listar(CANAL_ROCKSTAR, 400) if FILTRO_OFICIAL.search(e.get("title") or "")]
    if not vids:
        sys.exit("nenhum vídeo de GTA VI encontrado no canal da Rockstar")
    falhas = 0
    for e in vids:
        d = e.get("duration") or 0
        if d and d > max_min * 60:
            print(f"pulando (mais de {max_min} min): {e['title']}")
            continue
        if e["id"] in ja:
            print(f"já baixado: {e['title']}")
            continue
        print(f"\n>>> baixando: {e['title']} ({int(d // 60)}:{int(d % 60):02d})", flush=True)
        falhas += baixar(f"https://www.youtube.com/watch?v={e['id']}", pasta) != 0
    print(f"\n{len(vids)} vídeos oficiais encontrados, {falhas} falha(s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["oficiais", "pesquisar", "baixar"])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--trecho")
    ap.add_argument("--pasta", default="biblioteca/videos")
    ap.add_argument("--max-min", type=float, default=30)
    a = ap.parse_args()
    if a.acao == "oficiais":
        oficiais(a.pasta, a.max_min)
    elif a.acao == "pesquisar":
        pesquisar(a.alvo, a.n)
    else:
        sys.exit(baixar(a.alvo, a.pasta, a.trecho))


if __name__ == "__main__":
    main()
