"""Checagem antes de postar (vídeo narrado do Estúdio ou clipe cortado).

  python checar.py <video.mp4> [--tipo narrado|clipe] [--texto-arquivo post.txt] [--canal NOME] [--json saida.json]

Confere: 1080x1920, ~30 fps, tem áudio, duração, termos proibidos no texto do post/gancho (vazamento, "jogue antes",
pirataria, glitch de dinheiro...) e, nos clipes, o crédito ao criador no texto. Sai com código 1 se algo for ERRO.
(adaptado do rule-check do gtavi-claudecode, licença MIT)
"""
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ffprobe

PROIBIDOS = [
    r"\bleak(ed|s)?\b", r"leaked build", r"play(ing)? early", r"early access download", r"free download", r"\bcrack(ed)?\b",
    r"\bpiracy\b", r"\bpirated\b", r"mod menu", r"money glitch", r"afk bot",
    r"\bvaz(ou|amento|ado|ada)\b", r"jog(ue|ar|a) antes", r"antes do lan[cç]amento.{0,20}(baix|jog)", r"download gr[aá]tis",
    r"baix(e|ar) (de )?gr[aá]tis", r"\bpirat(a|aria|eado)\b", r"\bcrackead[oa]\b", r"glitch de dinheiro", r"dinheiro infinito",
    r"bot afk", r"menu de mod", r"\bapk\b",
]
OFICIAL = re.compile(r"\b(oficial da rockstar|rockstar oficial|official rockstar|somos a rockstar)\b", re.I)
LIMITES = {"narrado": (15, 180, 50, 80), "clipe": (5, 180, 7, 60)}   # erro fora de [a,b]; aviso fora de [c,d]


def _fps(s):
    try:
        a, b = s.split("/"); return float(a) / float(b)
    except Exception:
        return 0.0


def checar_video(video, texto="", tipo="narrado", canal=""):
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
