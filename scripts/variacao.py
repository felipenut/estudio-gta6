"""Variação de voz e música entre vídeos (ferramentas/variacao.json).

Modos (iguais para voz e música):
  fixa    -> sempre a mesma (voz_padrao / música 'tema*' como antes)
  serie   -> vídeos da mesma série (campo "serie" do roteiro) têm a mesma voz/música; sem série = rodízio
  rodizio -> a menos usada nos últimos vídeos

O roteiro sempre manda: "voz" ou "musica" escritos no roteiro.json não são trocados.
A escolha fica guardada em out/variacao.json, para refazer o vídeo com a mesma voz/música.
"""
import hashlib, json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
CONFIG = FERR / "variacao.json"
VOZES = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural", "pt-BR-MacerioMultilingualNeural"]
PADRAO = {"voz": "serie", "voz_padrao": "pt-BR-AntonioNeural", "vozes": VOZES, "musica": "serie"}
EXT_MUS = (".mp3", ".wav", ".m4a", ".ogg")


def config():
    c = dict(PADRAO)
    try:
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    c["vozes"] = [v for v in c.get("vozes") or [] if v] or [c["voz_padrao"]]
    return c


def salvar(c):
    atual = config()
    for k in ("voz", "voz_padrao", "vozes", "musica"):
        if k in c:
            atual[k] = c[k]
    if atual["voz"] not in ("fixa", "serie", "rodizio"):
        atual["voz"] = "serie"
    if atual["musica"] not in ("fixa", "serie", "rodizio"):
        atual["musica"] = "serie"
    CONFIG.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
    return atual


def _ler(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _registro(out):
    return _ler(Path(out) / "variacao.json")


def _gravar(out, **kw):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    r = _registro(out); r.update(kw)
    (out / "variacao.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def _recentes(projeto, campo, n=6):
    """Valores de 'campo' usados nos últimos n projetos (mais recente por último)."""
    projeto = Path(projeto).resolve()
    videos = projeto.parent
    res = []
    for d in sorted(videos.iterdir()):
        if d.resolve() == projeto or not d.is_dir():
            continue
        v = _registro(d / "out").get(campo)
        if v:
            res.append(v)
    return res[-n:]


def _escolher(opcoes, modo, serie, recentes, fixa):
    if not opcoes:
        return None
    if modo == "fixa":
        return fixa if fixa in opcoes else opcoes[0]
    if modo == "serie" and serie:
        return opcoes[int(hashlib.md5(serie.strip().lower().encode()).hexdigest(), 16) % len(opcoes)]
    # rodízio: a menos usada; empate -> a usada há mais tempo
    def chave(o):
        ult = max((i for i, r in enumerate(recentes) if r == o), default=-1)
        return (recentes.count(o), ult)
    return min(opcoes, key=chave)


def voz(rot, projeto, out):
    """Voz do vídeo: a do roteiro, a já escolhida antes, ou pela regra de variação."""
    if rot.get("voz"):
        return rot["voz"]
    ja = _registro(out).get("voz")
    if ja:
        return ja
    c = config()
    v = _escolher(c["vozes"], c["voz"], rot.get("serie", ""), _recentes(projeto, "voz"), c["voz_padrao"])
    v = v or c["voz_padrao"]
    _gravar(out, voz=v)
    return v


def musica(rot, projeto, out, pasta_musicas):
    """Nome do arquivo de música (dentro de pasta_musicas) ou None. Só é chamada quando o roteiro não define música."""
    pasta = Path(pasta_musicas)
    opcoes = sorted(p.name for p in pasta.iterdir() if p.suffix.lower() in EXT_MUS) if pasta.is_dir() else []
    if not opcoes:
        return None
    ja = _registro(out).get("musica")
    if ja in opcoes:
        return ja
    c = config()
    temas = [o for o in opcoes if o.lower().startswith("tema")]
    if c["musica"] == "fixa":
        m = _escolher(temas or opcoes, "serie", rot.get("titulo", "") or "x", [], None)
    else:
        m = _escolher(opcoes, c["musica"], rot.get("serie", ""), _recentes(projeto, "musica"), None)
    _gravar(out, musica=m)
    return m
