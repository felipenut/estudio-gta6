"""Funções compartilhadas pelo pipeline gta6-shorts."""
import json, re, shutil, subprocess, sys, unicodedata
from pathlib import Path

RAIZ_SKILL = Path(__file__).resolve().parent.parent
FONTES = RAIZ_SKILL / "assets" / "fonts"
W, H, FPS = 1080, 1920, 30


def ffmpeg_bin():
    for nome in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(nome)
        if p:
            return p
    sys.exit("ffmpeg não encontrado no PATH. Rode scripts/setup.py ou instale o ffmpeg.")


def ffprobe_bin():
    p = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not p:
        sys.exit("ffprobe não encontrado no PATH.")
    return p


def rodar(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        sys.stderr.write(" ".join(map(str, cmd)) + "\n" + r.stderr[-3000:] + "\n")
        raise SystemExit(f"comando falhou ({r.returncode})")
    return r


def duracao(arquivo):
    r = rodar([ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(arquivo)])
    return float(r.stdout.strip())


def tem_audio(arquivo):
    r = rodar([ffprobe_bin(), "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", str(arquivo)])
    return bool(r.stdout.strip())


def ler_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def salvar_json(p, dados):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def normalizar(palavra):
    """minúsculas, sem acento, só letras/números — para alinhar texto do roteiro com a narração."""
    s = unicodedata.normalize("NFD", palavra.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def tokens(texto):
    """Palavras do texto como aparecem na legenda (mantém pontuação colada)."""
    return [t for t in texto.split() if normalizar(t)]
