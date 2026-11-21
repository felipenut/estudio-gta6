"""Monta o vídeo final 9:16: corta os clipes, sincroniza com a narração, queima a legenda palavra-por-palavra
e mixa narração + música.

  python montar.py roteiro.json --saida out/ [--lib biblioteca/biblioteca.json] [--musica trilha.mp3]

Precisa de <saida>/narracao.mp3 e <saida>/palavras.json (gerados por narrar.py).
Saídas em <saida>/: final.mp4, legenda.ass, legenda.srt, timeline.json (usado por exportar_ae.py), folha_final.jpg
"""
import argparse, difflib, json, math, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import (ffmpeg_bin, ffprobe_bin, rodar, duracao, ler_json, salvar_json, normalizar, tokens,
                   FONTES, RAIZ_SKILL, W, H, FPS)
import biblioteca as B

ESTILO_PADRAO = {
    "fonte": "Bangers", "tamanho": 290, "cor": "&H00FFFFFF", "cor_destaque": "&H0000E5FF",
    "contorno": 14, "sombra": 5, "legenda_y": 1330, "maiusculas": True,
    "ritmo_corte": 2.4, "layout": "auto", "moldura_altura": 1090,
    "volume_musica": 0.13, "zoom": 0.06,
    "sfx": True, "volume_sfx": 0.45, "loudness": -14, "barra_progresso": False,
    "cartela_tamanho": 210, "cartela_y": 470,
}


# ---------------------------------------------------------------- alinhamento texto x narração
def alinhar(rot, palavras):
    roteiro_tok = []                                   # (seg_idx, palavra_como_escrita)
    for i, s in enumerate(rot["segmentos"]):
        roteiro_tok += [(i, t) for t in tokens(s["texto"])]
    a = [normalizar(t) for _, t in roteiro_tok]
    b = [normalizar(p["palavra"]) for p in palavras]
    tempos = [None] * len(a)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            p = palavras[blk.b + k]
            tempos[blk.a + k] = (p["inicio"], p["fim"])
    # preenche palavras não casadas (números falados por extenso etc.) interpolando
    fim_audio = palavras[-1]["fim"]
    i = 0
    while i < len(tempos):
        if tempos[i] is None:
            j = i
            while j < len(tempos) and tempos[j] is None:
                j += 1
            ini = tempos[i - 1][1] if i > 0 else 0.0
            fim = tempos[j][0] if j < len(tempos) else fim_audio
            passo = max(0.05, (fim - ini) / (j - i))
            for k in range(i, j):
                tempos[k] = (ini + (k - i) * passo, ini + (k - i + 1) * passo)
            i = j
        else:
            i += 1
    return [{"seg": s, "palavra": t, "inicio": round(tp[0], 3), "fim": round(tp[1], 3)}
            for (s, t), tp in zip(roteiro_tok, tempos)]


# ---------------------------------------------------------------- escolha de clipes
class Seletor:
    def __init__(self, lib_path):
        self.lib_path = Path(lib_path).resolve() if lib_path else None
        self.lib = ler_json(self.lib_path) if self.lib_path and self.lib_path.exists() else {"videos": []}
        self.base = self.lib_path.parent if self.lib_path else Path(".")
        self.cenas = {c["id"]: (v, c) for v in self.lib["videos"] for c in v["cenas"]}
        self.usadas = set()

    def caminho(self, arquivo):
        p = Path(arquivo)
        return p if p.is_absolute() else (self.base / p).resolve()

    def de_ref(self, ref):
        """ref: {"cena": id} | {"arquivo": path, "inicio": s, "fim"?: s, "foco"?: 0..1}"""
        if "cena" in ref:
            if ref["cena"] not in self.cenas:
                sys.exit(f"cena não encontrada na biblioteca: {ref['cena']}")
            v, c = self.cenas[ref["cena"]]
            self.usadas.add(c["id"])
            foco = ref.get("foco", c.get("foco"))
            return {"arquivo": self.caminho(v["arquivo"]), "inicio": c["inicio"], "fim": c["fim"],
                    "dur_video": v["duracao"], "foco": 0.5 if foco is None else foco,
                    "foco_fixo": foco is not None, "layout_cena": c.get("layout"),
                    "tags": c.get("tags", []), "descricao": c.get("descricao", ""), "id": c["id"]}
        arq = Path(ref["arquivo"]).resolve()
        return {"arquivo": arq, "inicio": float(ref.get("inicio", 0)), "fim": ref.get("fim"),
                "dur_video": duracao(arq), "foco": ref.get("foco", 0.5), "foco_fixo": "foco" in ref,
                "layout_cena": None, "tags": [], "descricao": "", "id": arq.name}

    def automatico(self, consulta, n):
        res = []
        for _, _, _, c in B.buscar(self.lib_path, consulta, n * 3, self.usadas) if self.lib_path else []:
            if len(res) >= n:
                break
            if TAGS_INTEIRO & set(c["tags"]) and not (TAGS_INTEIRO & set(consulta.split())):
                continue
            res.append({"cena": c["id"]})
            self.usadas.add(c["id"])
        if len(res) < n:                       # completa com cenas ainda não usadas (maiores primeiro)
            livres = sorted((c for v, c in self.cenas.values()
                            if c["id"] not in self.usadas and "ruim" not in c["tags"]
                            and not (TAGS_INTEIRO & set(c["tags"]))),
                            key=lambda c: -(c["fim"] - c["inicio"]))
            for c in livres[: n - len(res)]:
                res.append({"cena": c["id"]})
                self.usadas.add(c["id"])
        return res


def planejar_cortes(rot, alinhado, total, sel, est):
    segs = rot["segmentos"]
    inicios = []
    for i in range(len(segs)):
        ps = [p for p in alinhado if p["seg"] == i]
        inicios.append(ps[0]["inicio"] if ps else (inicios[-1] if inicios else 0.0))
    inicios[0] = 0.0
    cortes = []
    for i, s in enumerate(segs):
        t0, t1 = inicios[i], (inicios[i + 1] if i + 1 < len(segs) else total)
        d = t1 - t0
        if d <= 0.05:
            continue
        ritmo = s.get("ritmo_corte", est["ritmo_corte"])
        n = max(1, round(d / ritmo))
        refs = list(s.get("clipes", []))
        if not refs:                                   # sem escolha manual: busca automática
            consulta = " ".join([s.get("busca", "")] + s.get("tags", []))
            refs = sel.automatico(consulta, n)
        if not refs:
            sys.exit("biblioteca vazia e segmento sem clipes — indexe vídeos antes de montar")
        n = max(n, min(len(s.get("clipes", [])), math.floor(d / 0.8)))   # clipes escolhidos à mão: usa todos
        dc = d / n
        uso = {}
        for k in range(n):
            ref = refs[k % len(refs)]
            c = sel.de_ref(ref)
            off = uso.get(c["id"], 0.0)              # reaproveitando a mesma cena: avança no tempo
            src = c["inicio"] + off
            if c.get("fim") is not None and src + dc > c["fim"]:     # não vazar para o plano seguinte
                src = max(c["inicio"], c["fim"] - dc)
            src = max(0.0, min(src, c["dur_video"] - dc - 0.05))
            uso[c["id"]] = off + dc
            cortes.append({"seg": i, "ref_idx": k % len(refs), "t0": round(t0 + k * dc, 3), "dur": round(dc, 3),
                           "arquivo": str(c["arquivo"]), "src_in": round(src, 3), "cena": c["id"],
                           "cena_biblioteca": "cena" in ref, "foco": c["foco"], "foco_fixo": c["foco_fixo"], "tags": c["tags"], "descricao": c.get("descricao", ""),
                           "layout": ref.get("layout") or s.get("layout") or c["layout_cena"] or est["layout"],
                           "imagem": s.get("imagem"), "tipo": s.get("tipo", ""),
                           "zoom": ref.get("zoom", s.get("zoom", est["zoom"]))})
    return cortes


# ---------------------------------------------------------------- render
_DIMS = {}


def dims(arquivo):
    if arquivo not in _DIMS:
        r = rodar([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=width,height", "-of", "csv=p=0:s=x", str(arquivo)])
        w, h = r.stdout.strip().split("x")[:2]
        _DIMS[arquivo] = (int(w), int(h))
    return _DIMS[arquivo]


_CROPS = {}
_CACHE_ARQ = None                                       # out/cache_analise.json (tarjas + enquadramento automático)
_CACHE = {"tarjas": {}, "enq": {}}


def carregar_cache(out):
    global _CACHE_ARQ, _CACHE
    _CACHE_ARQ = Path(out) / "cache_analise.json"
    try:
        _CACHE = json.loads(_CACHE_ARQ.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = {"tarjas": {}, "enq": {}}
    _CACHE.setdefault("tarjas", {}); _CACHE.setdefault("enq", {})


def salvar_cache():
    if _CACHE_ARQ:
        _CACHE_ARQ.write_text(json.dumps(_CACHE), encoding="utf-8")


def tarjas(arquivo, ini, dur):
    """Detecta faixas pretas de cinema (letterbox) no trecho usado. Retorna (w, h, x, y) ou None."""
    chave = (arquivo, round(ini, 1), round(dur, 1))
    ck = f"{arquivo}|{chave[1]}|{chave[2]}"
    if chave not in _CROPS and ck in _CACHE["tarjas"]:
        v = _CACHE["tarjas"][ck]
        _CROPS[chave] = tuple(v) if v else None
    if chave not in _CROPS:
        r = rodar([ffmpeg_bin(), "-hide_banner", "-ss", f"{ini:.2f}", "-t", f"{max(dur, 0.5):.2f}", "-i", str(arquivo),
                   "-vf", "fps=4,cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"])
        import re
        achados = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        iw, ih = dims(arquivo)
        res = None
        if achados:
            w, h, x, y = map(int, achados[-1])
            # só aceita tarja horizontal clara (corta >= 4% da altura) e mantém a largura quase toda
            if h < ih * 0.96 and h > ih * 0.4 and w > iw * 0.9:
                res = (iw, h, 0, y)
        _CROPS[chave] = res
        _CACHE["tarjas"][ck] = list(res) if res else None
    return _CROPS[chave]


def zoom_expr(z, dur, idx):
    n = max(1, round((dur + 0.1) * FPS))
    return f"1+{z}*on/{n}" if idx % 2 == 0 else f"1+{z}*(1-on/{n})"


def zoompan(z, dur, idx, w, h):
    """push-in / pull-out suave, alternando a cada corte (fps antes para não mudar a velocidade)."""
    if z <= 0:
        return ""
    return (f",fps={FPS},zoompan=z='{zoom_expr(z, dur, idx)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={w}x{h}:fps={FPS}")


def filtro_layout(c, est, idx):
    """Layouts:
    inteiro (padrão) — quadro 16:9 INTEIRO na largura, centralizado, com o mesmo clipe desfocado atrás. Nada é cortado.
    cheio            — recorte 9:16 em tela cheia (corta as laterais; use `foco` para escolher a parte).
    moldura          — faixa central de altura moldura_altura (corta um pouco as laterais) com fundo desfocado."""
    z = float(c.get("zoom", est["zoom"]) or 0)
    iw, ih = dims(c["arquivo"])
    pre = ""
    t = tarjas(c["arquivo"], c["src_in"], c["dur"])
    if t:                                                  # remove as faixas pretas de cinema do trailer
        pre = f"crop={t[0]}:{t[1]}:{t[2]}:{t[3]},"
        iw, ih = t[0], t[1]
    layout = c["layout"] if c["layout"] != "auto" else "cheio"
    if layout == "inteiro" and ih * W / iw > H * 0.8:      # vídeo já vertical: não precisa de fundo
        layout = "cheio"
    f = c["foco"]
    if isinstance(f, (list, tuple)):                   # panorâmica: a janela desliza de f[0] até f[1]
        a, b = float(f[0]), float(f[1])
        fx = f"({a}+({b - a})*min(t/{max(c['dur'], 0.1):.3f},1))"
    else:
        fx = f"{float(f)}"
    cobrir = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:'(iw-{W})*{fx}':(ih-{H})/2")
    fundo = f"[a]{cobrir},boxblur=30:3,eq=brightness=-0.18:saturation=1.15[bg]"
    if layout == "inteiro":
        fh = int(round(ih * W / iw / 2) * 2)
        return (f"[0:v]{pre}split[a][b];{fundo};[b]scale={W}:{fh}{zoompan(z, c['dur'], idx, W, fh)}[fg];"
                f"[bg][fg]overlay=0:(H-h)/2")
    if layout == "moldura":
        mh = est["moldura_altura"]
        return (f"[0:v]{pre}split[a][b];{fundo};"
                f"[b]scale={W}:{mh}:force_original_aspect_ratio=increase,"
                f"crop={W}:{mh}:(iw-{W})*{fx}:(ih-{mh})/2{zoompan(z, c['dur'], idx, W, mh)}[fg];"
                f"[bg][fg]overlay=0:(H-h)/2")
    return f"[0:v]{pre}{cobrir}{zoompan(z, c['dur'], idx, W, H)}"


TAGS_INTEIRO = {"logo", "texto", "capa", "cover art", "data", "mapa", "anuncio"}


def hash_txt(t):
    import hashlib
    return hashlib.md5(t.encode("utf-8")).hexdigest()[:8]


def aplicar_enquadramentos(cortes, ajustes_projeto, salvos):
    """Um ajuste local tem prioridade sobre o enquadramento salvo da cena."""
    for i, corte in enumerate(cortes):
        ajuste = ajustes_projeto.get(str(i))
        motivo = "manual"
        if ajuste is None and corte.get("cena_biblioteca"):
            ajuste = salvos.get(corte["cena"])
            motivo = "salvo na biblioteca"
        if ajuste is None:
            continue
        corte["motivo"] = motivo
        if isinstance(ajuste, str):
            corte["layout"] = ajuste
        else:
            corte["layout"], corte["foco"] = "cheio", ajuste


def resolver_enquadramento(cortes, rot=None):
    """layout "auto": tela cheia com o recorte no assunto (rostos/pessoas/movimento/destaque);
    "inteiro" só para logo/texto/capa/mapa ou quando há pessoas espalhadas que não cabem no 9:16."""
    try:
        import enquadrar as E
    except Exception:
        E = None
    avisou = False
    for c in cortes:
        if c["layout"] != "auto":
            continue
        if TAGS_INTEIRO & set(c.get("tags", [])):
            c["layout"], c["motivo"] = "inteiro", "logo/texto"
            continue
        if E is None:
            if not avisou:
                print("aviso: OpenCV ausente (pip install \"opencv-python-headless<5\"); recorte centralizado")
                avisou = True
            c["layout"], c["motivo"] = "cheio", "centro"
            continue
        iw, ih = dims(c["arquivo"])
        t = tarjas(c["arquivo"], c["src_in"], c["dur"])
        fala = rot["segmentos"][c["seg"]].get("texto", "") if rot and c.get("seg") is not None else ""
        cena = " ".join(c.get("tags", [])) + " " + c.get("descricao", "")
        ck = f"{c['arquivo']}|{round(c['src_in'], 2)}|{round(c['dur'], 2)}|v3|{hash_txt(fala + '|' + cena)}"
        r = _CACHE["enq"].get(ck)
        if r is None:
            try:
                r = E.decidir(c["arquivo"], c["src_in"], c["dur"], t, iw, ih, fala=fala, cena=cena)
                _CACHE["enq"][ck] = r
            except Exception as e:
                r = {"foco": 0.5, "layout": "cheio", "motivo": f"erro: {e}"}
        c["layout"], c["motivo"] = r["layout"], r.get("motivo", "")
        if not c.get("foco_fixo"):
            c["foco"] = r["foco"]


def previa_enquadramento(cortes, destino):
    """Folha de revisão: um quadro do meio de cada corte, com a janela 9:16 desenhada (verde = tela cheia;
    azul = panorâmica, mostra início e fim; laranja = inteiro) e uma RÉGUA 0–1 em cima para ler/ajustar o `foco`.
    O `foco` é a posição da janela: 0 = encostada na esquerda, 1 = encostada na direita."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    import io, subprocess
    fonte = ImageFont.truetype(str(FONTES / "Bangers-Regular.ttf"), 22)
    mini = ImageFont.truetype(str(FONTES / "Bangers-Regular.ttf"), 16)
    tw, th, col, regua = 400, 200, 4, 18
    lin = (len(cortes) + col - 1) // col
    alt = th + 28 + regua
    folha = Image.new("RGB", (col * tw, lin * alt), "black")
    d = ImageDraw.Draw(folha)
    for i, c in enumerate(cortes):
        t = tarjas(c["arquivo"], c["src_in"], c["dur"])
        vf = (f"crop={t[0]}:{t[1]}:{t[2]}:{t[3]}," if t else "") + f"scale={tw}:-2"
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{c['src_in'] + c['dur'] / 2:.2f}", "-i",
                            str(c["arquivo"]), "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True)
        if r.returncode or not r.stdout:
            continue
        im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
        iw_, ih_ = im.size
        x0, y0 = (i % col) * tw, (i // col) * alt
        yi = y0 + regua + (th - ih_) // 2
        jan = int(round(ih_ * 9 / 16))
        for k in range(11):                                # régua: posição do centro da janela para cada foco
            xc = x0 + jan / 2 + k / 10 * (iw_ - jan)
            d.line([xc, y0 + 10, xc, y0 + regua], fill=(160, 160, 160), width=1)
            if k % 5 == 0:
                d.text((xc - 6, y0 - 1), f"{k / 10:g}", font=mini, fill=(200, 200, 200))
        if c["layout"] == "inteiro":
            folha.paste(im, (x0, yi))
            d.rectangle([x0 + 1, yi, x0 + tw - 2, yi + ih_ - 1], outline=(255, 140, 0), width=4)
            info = "INTEIRO"
        else:
            escuro = Image.eval(im, lambda v: v // 3)
            f = c["foco"]
            fs = f if isinstance(f, (list, tuple)) else [f]
            for fv in fs:
                xj = int(float(fv) * (iw_ - jan))
                escuro.paste(im.crop((xj, 0, xj + jan, ih_)), (xj, 0))
            folha.paste(escuro, (x0, yi))
            for n_, fv in enumerate(fs):
                xj = int(float(fv) * (iw_ - jan))
                cor = (0, 255, 0) if len(fs) == 1 else ((0, 170, 255) if n_ == 0 else (0, 90, 255))
                d.rectangle([x0 + xj, yi, x0 + xj + jan - 1, yi + ih_ - 1], outline=cor, width=3)
            info = "foco " + ("→".join(f"{float(v):.2f}" for v in fs))
        rot = f"{i} | seg {c['seg'] + 1} | {c['cena'].replace('GTA6_', '')[:20]} | {info}"
        d.text((x0 + 4, y0 + regua + th + 2), rot, font=fonte, fill="yellow")
    folha.save(destino, quality=85)


def caminho_asset(arq):
    """Caminho de imagem: absoluto, relativo à pasta atual, ou nome de um asset da skill (ex.: "seta_baixo.png")."""
    p = Path(arq)
    if p.exists():
        return p.resolve()
    q = RAIZ_SKILL / "assets" / p.name
    if q.exists():
        return q
    sys.exit(f"imagem não encontrada: {arq}")


def assinatura_corte(c, idx, est):
    """Tudo o que muda a imagem de um corte. Igual = reaproveita o arquivo já renderizado."""
    import hashlib
    arq = Path(c["arquivo"])
    try:
        mt = arq.stat().st_mtime
    except OSError:
        mt = 0
    chave = json.dumps([str(arq), mt, round(c["src_in"], 3), round(c["dur"], 3), c["layout"], c["foco"],
                        c.get("zoom"), idx % 2, c.get("imagem"), est["zoom"], est["moldura_altura"], 3],
                       sort_keys=True, default=str)
    return hashlib.md5(chave.encode()).hexdigest()[:16]


def render_corte(c, idx, tmp, est, cache=None):
    if cache is not None:
        saida = cache / f"{assinatura_corte(c, idx, est)}.mp4"
        if saida.exists() and saida.stat().st_size > 0:
            return saida, True
    else:
        saida = tmp / f"corte_{idx:03d}.mp4"
    fc = filtro_layout(c, est, idx)
    entradas = ["-ss", f"{c['src_in']:.3f}", "-t", f"{c['dur'] + 0.1:.3f}", "-i", c["arquivo"]]
    imgs = c.get("imagem") or []
    imgs = [imgs] if isinstance(imgs, dict) else imgs
    for k, img in enumerate(imgs, 1):
        entradas += ["-loop", "1", "-t", f"{c['dur'] + 0.1:.3f}", "-i", str(caminho_asset(img["arquivo"]))]
        larg = int(W * img.get("escala", 0.6))
        fc += (f"[b{k}];[{k}:v]scale={larg}:-1,format=rgba[im{k}];[b{k}][im{k}]overlay="
               f"{img.get('x', '(W-w)/2')}:{img.get('y', '220')}")
    fc += f",fps={FPS},format=yuv420p,setsar=1[v]"
    parcial = saida.with_suffix(".parcial.mp4")
    rodar([ffmpeg_bin(), "-y", "-v", "error", *entradas, "-filter_complex", fc, "-map", "[v]",
           "-t", f"{c['dur']:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           str(parcial)])
    parcial.replace(saida)
    return (saida, False) if cache is not None else saida


def tempo_ass(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def tempo_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def tempos_segmentos(cortes, n_seg, total):
    t = {}
    for c in cortes:
        a, b = t.get(c["seg"], (c["t0"], c["t0"]))
        t[c["seg"]] = (min(a, c["t0"]), max(b, c["t0"] + c["dur"]))
    return t


def escrever_ass(alinhado, rot, est, destino, total, tseg=None):
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Palavra,{est['fonte']},{est['tamanho']},{est['cor']},&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,2,0,1,{est['contorno']},{est['sombra']},5,40,40,0,1
Style: Cartela,{est['fonte']},{est['cartela_tamanho']},{est['cor_destaque']},&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,3,0,1,{est['contorno'] + 2},{est['sombra'] + 2},5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = []
    for k, p in enumerate(alinhado):
        ini = p["inicio"]
        prox = alinhado[k + 1]["inicio"] if k + 1 < len(alinhado) else total
        fim = min(prox, p["fim"] + 0.6) if prox - p["fim"] > 0.6 else prox
        fim = max(fim, ini + 0.08)
        txt = p["palavra"].strip(" ,;")
        txt = txt.upper() if est["maiusculas"] else txt
        cor = f"\\c{est['cor_destaque']}" if p.get("destaque") else ""
        anim = "\\fscx72\\fscy72\\t(0,80,\\fscx114\\fscy114)\\t(80,150,\\fscx100\\fscy100)"
        linhas.append(f"Dialogue: 0,{tempo_ass(ini)},{tempo_ass(fim)},Palavra,,0,0,0,,"
                      f"{{\\pos({W // 2},{est['legenda_y']}){anim}{cor}}}{txt.replace('{', '(').replace('}', ')')}")
    for i, seg in enumerate(rot["segmentos"]):        # cartelas: texto grande fixo durante o segmento
        cart = seg.get("cartela")
        if not cart or not tseg or i not in tseg:
            continue
        cart = {"texto": cart} if isinstance(cart, str) else cart
        a, b = tseg[i]
        y = cart.get("y", est["cartela_y"])
        txt = cart["texto"].upper().replace("{", "(").replace("}", ")").replace("\n", "\\N")
        anim = "\\fad(60,120)\\fscx60\\fscy60\\t(0,120,\\fscx108\\fscy108)\\t(120,200,\\fscx100\\fscy100)"
        rot_ = "\\q0" + (f"\\frz{cart['inclinacao']}" if "inclinacao" in cart else "\\frz-4")
        linhas.append(f"Dialogue: 1,{tempo_ass(a)},{tempo_ass(b)},Cartela,,0,0,0,,"
                      f"{{\\pos({W // 2},{y}){rot_}{anim}}}{txt}")
    Path(destino).write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")


def escrever_srt(alinhado, destino, por_bloco=4):
    blocos, out = [alinhado[i:i + por_bloco] for i in range(0, len(alinhado), por_bloco)], []
    for n, b in enumerate(blocos, 1):
        out.append(f"{n}\n{tempo_srt(b[0]['inicio'])} --> {tempo_srt(b[-1]['fim'])}\n"
                   + " ".join(p["palavra"] for p in b) + "\n")
    Path(destino).write_text("\n".join(out), encoding="utf-8")


def folha_final(video, destino, total):
    n = 12
    rodar([ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-vf",
           f"fps={n / total:.5f},scale=270:480,tile=6x2", "-frames:v", "1", str(destino)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roteiro")
    ap.add_argument("--saida", default="out")
    ap.add_argument("--lib", default="biblioteca/biblioteca.json")
    ap.add_argument("--musica")
    ap.add_argument("--so-plano", action="store_true", help="só gera timeline.json/legendas, sem renderizar")
    ap.add_argument("--so-capa", action="store_true", help="só refaz a capa.jpg (precisa de um vídeo já gerado)")
    ap.add_argument("--lote", action="store_true", help="pula folhas de contato auxiliares")
    a = ap.parse_args()
    if a.so_capa:
        out = Path(a.saida).resolve()
        rot = ler_json(a.roteiro)
        tl = ler_json(out / "timeline.json")
        if not (out / "video_mudo.mp4").exists():
            sys.exit("gere o vídeo uma vez antes de refazer só a capa")
        capa(out, rot, {**ESTILO_PADRAO, **rot.get("estilo", {})}, tl["cortes"])
        print(f"ok: {out / 'capa.jpg'}")
        return

    rot = ler_json(a.roteiro)
    est = {**ESTILO_PADRAO, **rot.get("estilo", {})}
    out = Path(a.saida).resolve(); out.mkdir(parents=True, exist_ok=True)
    narr = out / "narracao.mp3"
    palavras = ler_json(out / "palavras.json")
    total = round(duracao(narr) + 0.35, 3)

    alinhado = alinhar(rot, palavras)
    for p in alinhado:
        p["destaque"] = normalizar(p["palavra"]) in {
            normalizar(w) for w in rot["segmentos"][p["seg"]].get("destaque", [])}
    sel = Seletor(a.lib if Path(a.lib).exists() else None)
    cortes = planejar_cortes(rot, alinhado, total, sel, est)
    carregar_cache(out)
    salvos = (ler_json(Path(a.lib).with_name("_enquadramentos.json"))
              if Path(a.lib).with_name("_enquadramentos.json").exists() else {})
    aplicar_enquadramentos(cortes, rot.get("enquadramento") or {}, salvos)
    resolver_enquadramento(cortes, rot)
    salvar_cache()
    musica = a.musica or rot.get("musica")
    if musica in ("nenhuma", "sem"):
        musica = None
    elif musica and not Path(musica).exists() and (Path("musicas") / Path(musica).name).exists():
        musica = str(Path("musicas") / Path(musica).name)
    elif not musica and Path("musicas").is_dir():      # sem música no roteiro: regra de variação (variacao.json)
        try:
            import variacao
            nome_m = variacao.musica(rot, Path(a.roteiro).resolve().parent, out, "musicas")
        except Exception as e:
            print(f"aviso: variação de música desligada ({e})")
            import random
            opcoes = sorted(p.name for p in Path("musicas").iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))
            nome_m = random.Random(rot.get("titulo", "")).choice(opcoes) if opcoes else None
        if nome_m:
            musica = str(Path("musicas") / nome_m)
            print(f"música: {musica}")
    tseg = tempos_segmentos(cortes, len(rot["segmentos"]), total)
    cartelas = []
    for i, sg in enumerate(rot["segmentos"]):
        if sg.get("cartela") and i in tseg:
            ct = {"texto": sg["cartela"]} if isinstance(sg["cartela"], str) else dict(sg["cartela"])
            cartelas.append({"texto": ct["texto"].upper(), "inicio": tseg[i][0], "fim": tseg[i][1],
                             "y": ct.get("y", est["cartela_y"])})
    salvar_json(out / "timeline.json", {"total": total, "largura": W, "altura": H, "fps": FPS,
                                        "estilo": est, "narracao": str(narr),
                                        "musica": str(Path(musica).resolve()) if musica else None,
                                        "sfx": str(out / "sfx.wav") if est["sfx"] else None,
                                        "cortes": cortes, "palavras": alinhado, "cartelas": cartelas})
    fontes = out / "fonts"; fontes.mkdir(exist_ok=True)
    for f in FONTES.glob("*.ttf"):
        shutil.copy(f, fontes / f.name)
    escrever_ass(alinhado, rot, est, out / "legenda.ass", total, tseg)
    escrever_srt(alinhado, out / "legenda.srt")
    if a.so_plano or (not a.lote and not (out / "previa_enquadramento.jpg").exists()):
        previa_enquadramento(cortes, out / "previa_enquadramento.jpg")
        salvar_cache()
    print(f"plano: {len(cortes)} cortes, {len(alinhado)} palavras, {total:.1f}s")
    if a.so_plano:
        return

    tmp = out / "tmp"; tmp.mkdir(exist_ok=True)
    cache = out / "cache_cortes"; cache.mkdir(exist_ok=True)
    lista, reaproveitados = [], 0
    for i, c in enumerate(cortes):
        arq_corte, veio_do_cache = render_corte(c, i, tmp, est, cache)
        reaproveitados += veio_do_cache
        print(f"  corte {i + 1}/{len(cortes)}  {Path(c['arquivo']).name} @ {c['src_in']:.1f}s"
              + ("  (reaproveitado)" if veio_do_cache else ""), flush=True)
        lista.append(arq_corte)
    for velho in cache.glob("*.mp4"):                    # limpa cortes que não são mais usados
        if velho not in lista:
            velho.unlink(missing_ok=True)
    salvar_cache()
    if reaproveitados:
        print(f"{reaproveitados} de {len(cortes)} cortes reaproveitados do cache")
    (tmp / "lista.txt").write_text("".join(f"file '../cache_cortes/{p.name}'\n" for p in lista), encoding="utf-8")
    rodar([ffmpeg_bin(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
           "-c", "copy", "../video_mudo.mp4"], cwd=tmp)

    sfx = None
    if est["sfx"]:
        sfx = trilha_sfx(out, tmp, rot, cortes, alinhado, total, est)

    # passo final (cwd=out para o filtro ass não sofrer com caminhos do Windows)
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", "video_mudo.mp4", "-i", "narracao.mp3"]
    partes, n_in = ["[1:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[nar][nsc]"], 2
    mix = ["[nar]"]
    if musica:
        cmd += ["-stream_loop", "-1", "-i", str(Path(musica).resolve())]
        partes += [f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,volume={est['volume_musica']}[mus]",
                   "[mus][nsc]sidechaincompress=threshold=0.05:ratio=4:attack=20:release=300[duck]"]
        mix.append("[duck]"); n_in += 1
    else:
        partes.append("[nsc]anullsink")
    if sfx:
        cmd += ["-i", sfx.name]
        partes.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo[sfx]")
        mix.append("[sfx]"); n_in += 1
    alvo = est["loudness"]
    partes.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                  f"loudnorm=I={alvo}:TP=-1.5:LRA=11,aresample=48000[a]")
    v = "[0:v]ass=legenda.ass:fontsdir=fonts"
    if est["barra_progresso"]:
        v += (f",drawbox=x=0:y=0:w=iw:h=14:color=black@0.45:t=fill,"
              f"drawbox=x=0:y=0:w='iw*t/{total}':h=14:color=0x{cor_rgb_hex(est['cor_destaque'])}@0.95:t=fill")
    fc = f"{v}[v];" + ";".join(partes)
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "final.parcial.mp4"]
    rodar(cmd, cwd=out)
    corrigir_loudness(out, alvo, "final.parcial.mp4")
    if not a.lote:
        folha_final(out / "final.parcial.mp4", out / "folha_final.jpg", total)
    capa(out, rot, est, cortes)
    (out / "final.parcial.mp4").replace(out / "final.mp4")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"ok: {out / 'final.mp4'}  (+ capa.jpg, legenda.srt)")


# ---------------------------------------------------------------- efeitos sonoros
SFX_RECEITAS = {   # sintetizados pelo ffmpeg: sem baixar nada
    "impacto": "aevalsrc='0.9*sin(2*PI*(70-90*t)*t)*exp(-5*t)+0.25*random(0)*exp(-30*t)':d=0.7:s=48000,lowpass=f=900",
    "whoosh": "anoisesrc=d=0.42:c=pink:a=0.7:r=48000,bandpass=f=1500:width_type=o:w=2,"
              "afade=t=in:d=0.26:curve=exp,afade=t=out:st=0.26:d=0.16",
    "pop": "aevalsrc='0.7*sin(2*PI*(1300-7000*t)*t)*exp(-45*t)':d=0.1:s=48000",
}


def trilha_sfx(out, tmp, rot, cortes, alinhado, total, est):
    """impacto no início, whoosh em cada troca de assunto (segmento), pop nas palavras em destaque."""
    for nome, receita in SFX_RECEITAS.items():
        f = tmp / f"{nome}.wav"
        if not f.exists():
            rodar([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", receita, "-ac", "1", str(f)])
    eventos = [("impacto", 0.0, 1.0)]
    vistos = {0}
    for c in cortes:
        if c["seg"] not in vistos:
            vistos.add(c["seg"])
            eventos.append(("whoosh", max(0.0, c["t0"] - 0.2), 0.8))
    for p in alinhado:
        if p.get("destaque"):
            eventos.append(("pop", p["inicio"], 0.6))
    for i, s in enumerate(rot["segmentos"]):        # efeitos extras pedidos no roteiro: "sfx": "impacto"
        if s.get("sfx") in SFX_RECEITAS:
            t0 = min((c["t0"] for c in cortes if c["seg"] == i), default=None)
            if t0 is not None:
                eventos.append((s["sfx"], t0, 1.0))
    cmd = [ffmpeg_bin(), "-y", "-v", "error"]
    fc = []
    for k, (nome, t, vol) in enumerate(eventos):
        cmd += ["-i", str(tmp / f"{nome}.wav")]
        ms = int(t * 1000)
        fc.append(f"[{k}:a]volume={vol * est['volume_sfx']},adelay={ms}|{ms}[e{k}]")
    fc.append("".join(f"[e{k}]" for k in range(len(eventos)))
              + f"amix=inputs={len(eventos)}:normalize=0:duration=longest,apad,atrim=0:{total}[s]")
    destino = out / "sfx.wav"
    rodar(cmd + ["-filter_complex", ";".join(fc), "-map", "[s]", str(destino)])
    return destino


def corrigir_loudness(out, alvo, arquivo="final.mp4"):
    """2ª passada: mede o loudness integrado do final.mp4 e corrige o ganho (o loudnorm de 1 passada erra ~2 LU)."""
    import json as _json, re as _re
    r = rodar([ffmpeg_bin(), "-hide_banner", "-i", arquivo, "-vn", "-af",
               f"loudnorm=I={alvo}:TP=-1.5:print_format=json", "-f", "null", "-"], cwd=out)
    m = _re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    if not m:
        return
    medido = float(_json.loads(m.group(0))["input_i"])
    ganho = alvo - medido
    if abs(ganho) < 0.7:
        return
    rodar([ffmpeg_bin(), "-y", "-v", "error", "-i", arquivo, "-c:v", "copy", "-af",
           f"volume={ganho:.2f}dB,alimiter=limit=0.84:level=false", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "final_tmp.mp4"], cwd=out)
    (out / "final_tmp.mp4").replace(out / arquivo)
    print(f"loudness: {medido:.1f} -> {alvo} LUFS")


def cor_rgb_hex(ass):
    h = ass.replace("&H", "").replace("&", "")[-6:]
    return h[4:6] + h[2:4] + h[0:2]


# ---------------------------------------------------------------- capa
def capa(out, rot, est, cortes):
    """capa.jpg: quadro do gancho + título grande (para a capa do TikTok/Reels)."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        return
    texto = (rot.get("capa") or rot.get("titulo") or "").upper()
    quadro = out / "capa_base.jpg"
    cq = rot.get("capa_quadro") or {}
    if "tempo" in cq:                                  # momento exato do vídeo (segundos)
        t = float(cq["tempo"])
    elif "corte" in cq and 0 <= int(cq["corte"]) < len(cortes):
        c = cortes[int(cq["corte"])]
        t = c["t0"] + c["dur"] / 2
    else:
        t = min(0.8, cortes[0]["dur"] / 2)
    rodar([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(out / "video_mudo.mp4"),
           "-frames:v", "1", str(quadro)])
    im = Image.open(quadro).convert("RGB")
    if texto:
        grad = Image.new("L", (1, H))
        for yy in range(H):                         # escurece o topo para o título ler bem
            grad.putpixel((0, yy), int(170 * max(0.0, 1 - yy / (H * 0.55))))
        preto = Image.new("RGB", (W, H), "black")
        im = Image.composite(preto, im, grad.resize((W, H)))
        d = ImageDraw.Draw(im)
        tam = 170
        fonte = ImageFont.truetype(str(FONTES / "Bangers-Regular.ttf"), tam)
        palavras, linhas, atual = texto.split(), [], ""
        for w in palavras:                         # quebra em linhas que caibam em ~90% da largura
            teste = (atual + " " + w).strip()
            if d.textlength(teste, font=fonte) > W * 0.9 and atual:
                linhas.append(atual); atual = w
            else:
                atual = teste
        linhas.append(atual)
        y = int(H * 0.16)
        for k, linha in enumerate(linhas):
            cor = (255, 229, 0) if k % 2 == 0 else (255, 255, 255)
            larg = d.textlength(linha, font=fonte)
            d.text(((W - larg) / 2, y), linha, font=fonte, fill=cor, stroke_width=12, stroke_fill="black")
            y += int(tam * 1.02)
    im.save(out / "capa.jpg", quality=92)
    quadro.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
