"""Funções comuns dos cortes (adaptado do gtavi-claudecode, licença MIT, para o Estúdio GTA 6).

Tudo fica em <pasta de dados>/cortes/<trabalho>/ : source.mp4, info.json, transcript.json, candidates.json,
edits/clip_<n>.mp4 (+ .json) e live/ (gravações ao vivo).
"""
import hashlib, json, os, re, shutil, subprocess, sys
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


# ------------------------------------------------------------------ codificador de vídeo (placa de vídeo ou CPU)
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
CODIFICADORES = (   # na ordem de preferência; todos saem em H.264 1080x1920, aceitos por TikTok/YouTube/Instagram
    ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "21", "-b:v", "0",
                    "-maxrate", "16M", "-bufsize", "32M", "-pix_fmt", "yuv420p"]),
    ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "faster", "-global_quality", "22", "-look_ahead", "0",
                  "-pix_fmt", "nv12"]),
    ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22",
                  "-pix_fmt", "nv12"]),
)


def _arquivo_codificador():
    return ROOT / "_codificador.json"


def codificador_video():
    """Argumentos do codificador mais rápido que funciona neste PC (NVIDIA, Intel ou AMD; senão x264).
    O teste roda uma vez e fica guardado em cortes/_codificador.json. ESTUDIO_CODIFICADOR=x264 força a CPU."""
    forcado = os.environ.get("ESTUDIO_CODIFICADOR", "").strip().lower()
    if forcado in ("x264", "libx264", "cpu"):
        return list(X264)
    ffmpeg = tool("ffmpeg")
    try:
        chave = f"{ffmpeg}|{Path(ffmpeg).stat().st_mtime:.0f}"
    except OSError:
        chave = ffmpeg
    salvo = {}
    try:
        salvo = json.loads(_arquivo_codificador().read_text(encoding="utf-8"))
    except Exception:
        pass
    if salvo.get("chave") == chave and salvo.get("nome"):
        return list(dict(CODIFICADORES).get(salvo["nome"], X264))
    escolhido = "libx264"
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    for nome, args in CODIFICADORES:
        if forcado and forcado != nome:
            continue
        teste = [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=0.5", *args, "-f", "null", "-"]
        try:
            r = subprocess.run(teste, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, **kw)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            escolhido = nome
            break
    try:
        save_json(_arquivo_codificador(), {"chave": chave, "nome": escolhido})
    except OSError:
        pass
    print(f"   codificador de vídeo: {escolhido}" + ("" if escolhido == "libx264" else " (placa de vídeo)"), flush=True)
    return list(dict(CODIFICADORES).get(escolhido, X264))


def _com_x264(cmd):
    """Troca o codificador de placa de vídeo pelo x264 (para tentar de novo se a placa falhar)."""
    cmd = list(cmd)
    if "-c:v" not in cmd:
        return None
    i = cmd.index("-c:v")
    if cmd[i + 1] == "libx264" or "-pix_fmt" not in cmd[i:]:
        return None
    j = cmd.index("-pix_fmt", i)
    return cmd[:i] + X264 + cmd[j + 2:]


def _desativar_placa():
    try:
        dados = json.loads(_arquivo_codificador().read_text(encoding="utf-8"))
        dados["nome"] = "libx264"
        save_json(_arquivo_codificador(), dados)
    except Exception:
        pass


def executar_render(cmd, duracao=None):
    """Renderiza; se o codificador da placa de vídeo falhar, refaz com x264 e passa a usar a CPU."""
    try:
        if duracao:
            return renderizar_com_progresso(cmd, duracao)
        return run(cmd)
    except SystemExit:
        reserva = _com_x264([str(c) for c in cmd])
        if not reserva:
            raise
        print("   a placa de vídeo falhou neste corte; refazendo com o processador (x264)…", flush=True)
        _desativar_placa()
        if duracao:
            return renderizar_com_progresso(reserva, duracao)
        return run(reserva)


def renderizar_com_progresso(cmd, duracao):
    """Executa o FFmpeg de um corte e informa o avanço sem mudar o vídeo gerado."""
    cmd = [str(c) for c in cmd]
    cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kw)
    instante_us, ultimo = 0, -1
    try:
        for linha in proc.stdout:
            chave, _, valor = linha.strip().partition("=")
            if chave in ("out_time_us", "out_time_ms"):
                try:
                    instante_us = int(valor)  # Ambos são microssegundos no protocolo do FFmpeg.
                except ValueError:
                    continue
            elif chave == "progress" and duracao > 0:
                pct = max(0, min(100, int(instante_us / (duracao * 1000000) * 100)))
                if valor == "end":
                    pct = 100
                if pct != ultimo:
                    print(f"renderização: {pct}%", flush=True)
                    ultimo = pct
    finally:
        proc.stdout.close()
        codigo = proc.wait()
    if codigo:
        sys.exit(f"renderização falhou ({codigo})")


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
