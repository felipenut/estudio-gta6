"""Funções comuns dos cortes (adaptado do gtavi-claudecode, licença MIT, para o Estúdio GTA 6).

Tudo fica em <pasta de dados>/cortes/<trabalho>/ : source.mp4, info.json, transcript.json, candidates.json,
edits/clip_<n>.mp4 (+ .json) e live/ (gravações ao vivo).
"""
import hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

CLIPES = Path(__file__).resolve().parent            # ferramentas/scripts/clipes
SCRIPTS = CLIPES.parent                              # ferramentas/scripts
FERR = SCRIPTS.parent                                # ferramentas
RAIZ = FERR.parent                                   # pasta de dados (skill-gta6)
ROOT = RAIZ / "cortes"
JOBS = ROOT


def tool(name):
    p = shutil.which(name) or shutil.which(name + ".exe")
    if not p:
        sys.exit(f"{name} não encontrado. Reinstale o Estúdio (ele traz o ffmpeg).")
    return p


def run(cmd, check=True, capture=False):
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    r = subprocess.run([str(c) for c in cmd], check=False, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None, **kw)
    if check and r.returncode != 0:
        msg = (r.stderr or "")[-1500:] if capture else ""
        sys.exit(f"comando falhou ({r.returncode}): {' '.join(map(str, cmd))[:200]}\n{msg}")
    return r


def ytdlp_base():
    """O mesmo yt-dlp do Estúdio (Python embutido + deno para o YouTube)."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from baixar import ytdlp
        return ytdlp()
    except Exception:
        import importlib.util
        return ([sys.executable, "-m", "yt_dlp"] if importlib.util.find_spec("yt_dlp") else [tool("yt-dlp")]) + ["--no-warnings"]


def ytdlp_json(url, extra=()):
    r = run(ytdlp_base() + ["-J", *extra, url], capture=True)
    return json.loads(r.stdout)


def is_url(s):
    return bool(re.match(r"https?://", s))


def job_name(src):
    key = hashlib.sha1(src.encode()).hexdigest()[:8]
    if is_url(src):
        base = src.split("v=")[-1].split("&")[0].rstrip("/").split("/")[-1]
    else:
        base = Path(src).stem
    stem = re.sub(r"[^a-z0-9]+", "-", base.lower())[:24].strip("-")
    return f"{stem or 'corte'}-{key}"


def job_dir(src):
    d = JOBS / job_name(src)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffprobe(path):
    r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", str(path)], capture=True)
    return json.loads(r.stdout)


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
