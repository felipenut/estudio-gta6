"""Checagem antes de postar (vídeo narrado do Estúdio ou clipe cortado).

  python checar.py <video.mp4> [--tipo narrado|clipe] [--texto-arquivo post.txt] [--canal NOME] [--json saida.json]

Confere: 1080x1920, ~30 fps, tem áudio, duração, termos proibidos no texto do post/gancho (vazamento, "jogue antes",
pirataria, glitch de dinheiro...) e, nos clipes, o crédito ao criador no texto. Sai com código 1 se algo for ERRO.
Retenção (avisos, não barram): silêncio longo, gancho nos 3 primeiros segundos, fala que demora a começar,
legenda/gancho fora da zona segura (com o clip_N.json do corte) e pergunta aberta no post.
(adaptado do rule-check do gtavi-claudecode, licença MIT)
"""
import argparse, json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ffprobe, tool

PROIBIDOS = [
    r"\bleak(ed|s)?\b", r"leaked build", r"play(ing)? early", r"early access download", r"free download", r"\bcrack(ed)?\b",
    r"\bpiracy\b", r"\bpirated\b", r"mod menu", r"money glitch", r"afk bot",
    r"\bvaz(ou|amento|ado|ada)\b", r"jog(ue|ar|a) antes", r"antes do lan[cç]amento.{0,20}(baix|jog)", r"download gr[aá]tis",
    r"baix(e|ar) (de )?gr[aá]tis", r"\bpirat(a|aria|eado)\b", r"\bcrackead[oa]\b", r"glitch de dinheiro", r"dinheiro infinito",
    r"bot afk", r"menu de mod", r"\bapk\b",
]
OFICIAL = re.compile(r"\b(oficial da rockstar|rockstar oficial|official rockstar|somos a rockstar)\b", re.I)
LIMITES = {"narrado": (15, 180, 50, 80), "clipe": (5, 180, 15, 45)}  # erro fora de [a,b]; aviso fora de [c,d]
ZONA = {"topo": 220, "baixo": 1500}                 # TikTok/Reels/Shorts: fora disso a interface da plataforma cobre
SILENCIO_DB, SILENCIO_S = -40, 1.2


def _fps(s):
    try:
        a, b = s.split("/"); return float(a) / float(b)
    except Exception:
        return 0.0


def silencios(video, limite_db=SILENCIO_DB, minimo=SILENCIO_S):
    """Trechos de silêncio (início, fim) com o silencedetect do ffmpeg."""
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                        f"silencedetect=noise={limite_db}dB:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    ini, out = None, []
    for ln in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", ln)
        if m:
            ini = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", ln)
        if m and ini is not None:
            out.append((ini, float(m.group(1)))); ini = None
    return out


def meta_do_corte(video):
    """clip_N.json ao lado do clip_N.mp4 (gravado pelo cut.py), se existir."""
    side = Path(video).with_suffix(".json")
    try:
        return json.loads(side.read_text(encoding="utf-8")) if side.exists() else None
    except Exception:
        return None


def checar_video(video, texto="", tipo="narrado", canal="", meta=None):
    itens = []

    def add(nome, ok, detalhe="", nivel="erro"):
        itens.append({"nome": nome, "ok": bool(ok), "nivel": "ok" if ok else nivel, "detalhe": detalhe})

    video = Path(video)
    if not video.exists():
        add("arquivo do vídeo", False, "não encontrado")
        return {"ok": False, "itens": itens}
    p = ffprobe(video)
    streams = p.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    au = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(p.get("format", {}).get("duration", 0) or 0)
    add("formato vertical 1080x1920", bool(v) and (v.get("width"), v.get("height")) == (1080, 1920),
        f"{v.get('width')}x{v.get('height')}" if v else "sem vídeo")
    f = _fps(v.get("r_frame_rate", "0/1")) if v else 0
    add("cerca de 30 quadros/s", 23 <= f <= 61, f"{f:.0f} fps", "aviso")
    add("tem áudio", au is not None, "" if au else "sem faixa de som")
    a, b, c, d = LIMITES.get(tipo, LIMITES["narrado"])
    if not (a <= dur <= b):
        add(f"duração entre {a} e {b} s", False, f"{dur:.1f} s")
    else:
        add(f"duração ideal {c}–{d} s", c <= dur <= d, f"{dur:.1f} s", "aviso")
    low = (texto or "").lower()
    achados = sorted({m.group(0) for rx in PROIBIDOS for m in [re.search(rx, low, re.I)] if m})
    add("sem termos proibidos no post (vazamento, jogue antes, pirataria, glitch)", not achados, ", ".join(achados))
    add("não se passa pela Rockstar", not OFICIAL.search(texto or ""), "o texto diz ser oficial da Rockstar")
    add("texto do post preenchido", bool((texto or "").strip()), "post.txt vazio", "aviso")
    if tipo == "clipe":
        cred = bool(canal) and canal.lower().lstrip("@") in low
        add("crédito ao criador no texto do post", cred or bool(re.search(r"(via|cr[eé]dito|credit|by|fonte)\s*:?\s*@?\w", low)),
            f"escreva no post: via @{canal}" if canal else "escreva no post de quem é o vídeo original")
    # ---- retenção (só avisos)
    try:
        sil = [x for x in silencios(video) if x[1] - x[0] >= SILENCIO_S]
    except Exception:
        sil = []
    add("sem silêncio longo (pausa morta derruba a retenção)", not sil,
        ", ".join(f"{a:.1f}–{b:.1f}s" for a, b in sil[:4]), "aviso")
    if tipo == "clipe":
        meta = meta if meta is not None else meta_do_corte(video)
        if meta:
            rp = meta.get("render") or {}
            gancho = (meta.get("title") or meta.get("hook") or "").strip()
            secs = float(rp.get("title_secs") or 4)
            add("gancho na tela nos 3 primeiros segundos", bool(gancho) and secs >= 3,
                "sem texto de gancho" if not gancho else f"só {secs:.0f} s", "aviso")
            pf = meta.get("primeira_fala")
            if pf is not None:
                add("a fala começa logo (até 2 s)", pf <= 2.0, f"começa em {pf:.1f} s", "aviso")
            fora = []
            cy = rp.get("cap_y")
            if cy is not None and not (ZONA["topo"] <= cy <= ZONA["baixo"]):
                fora.append(f"legenda em y={cy}")
            ty = rp.get("texto_y_final") or rp.get("texto_y")
            if ty is not None and not (ZONA["topo"] <= ty <= ZONA["baixo"]):
                fora.append(f"gancho em y={ty}")
            add("legenda e gancho dentro da zona segura", not fora, ", ".join(fora), "aviso")
    add("pergunta aberta no post (puxa comentários)", "?" in (texto or ""), "sem pergunta no texto do post", "aviso")
    erros = [i for i in itens if i["nivel"] == "erro"]
    return {"ok": not erros, "itens": itens, "duracao": round(dur, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--tipo", choices=list(LIMITES), default="narrado")
    ap.add_argument("--texto", default=""); ap.add_argument("--texto-arquivo"); ap.add_argument("--canal", default="")
    ap.add_argument("--json")
    a = ap.parse_args()
    texto = a.texto
    if a.texto_arquivo and Path(a.texto_arquivo).exists():
        texto = Path(a.texto_arquivo).read_text(encoding="utf-8", errors="replace")
    r = checar_video(a.video, texto, a.tipo, a.canal)
    for i in r["itens"]:
        marca = {"ok": "OK   ", "aviso": "AVISO", "erro": "ERRO "}[i["nivel"]]
        print(f"{marca} {i['nome']}" + (f"  [{i['detalhe']}]" if i["detalhe"] and not i["ok"] else ""))
    print("RESULTADO: " + ("PASSOU" if r["ok"] else "NÃO PASSOU"))
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
