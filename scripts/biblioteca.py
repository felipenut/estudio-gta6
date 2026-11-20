"""Biblioteca de clipes de GTA: indexa vídeos em cenas, gera folhas de miniaturas e busca por tags.

  python biblioteca.py indexar <pasta_videos> [--lib biblioteca/biblioteca.json]
  python biblioteca.py pendentes [--lib ...]       # lista folhas de miniaturas de cenas ainda sem tags
  python biblioteca.py buscar "lucia praia carro" [--n 8] [--lib ...]
  python biblioteca.py marcar tags.json [--lib ...]   # aplica descrições/tags em lote:
        {"<id da cena>": {"d": "descrição", "t": ["tag", ...], "foco": 0.4}, ...}
        (atalho: "<id>": ["descrição", ["tag", ...]]; para descartar: "<id>": "ruim")

Depois de indexar, Claude abre cada folha (miniaturas/<video>_folha_N.jpg), descreve as cenas e
preenche "descricao" e "tags" no biblioteca.json (ver references/biblioteca.md).
"""
import argparse, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ffmpeg_bin, rodar, duracao, ler_json, salvar_json, normalizar, FONTES

EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
MIN_CENA, MAX_CENA = 1.2, 6.0


def detectar_cortes(video, limiar=0.3):
    r = rodar([ffmpeg_bin(), "-hide_banner", "-i", str(video), "-an", "-vf",
               f"scale=320:-2,select='gt(scene,{limiar})',showinfo", "-f", "null", "-"])
    return sorted(float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr))


def cenas_de(video):
    dur = duracao(video)
    marcos = [0.0] + [c for c in detectar_cortes(video) if 0 < c < dur] + [dur]
    brutas = []
    for a, b in zip(marcos, marcos[1:]):
        if brutas and b - a < MIN_CENA:      # cena curta demais: junta na anterior
            brutas[-1][1] = b
        else:
            brutas.append([a, b])
    cenas = []
    for a, b in brutas:                      # cena longa: fatia em pedaços de ~4s
        n = max(1, round((b - a) / 4.0)) if b - a > MAX_CENA else 1
        passo = (b - a) / n
        for i in range(n):
            cenas.append((round(a + i * passo, 2), round(a + (i + 1) * passo, 2)))
    return dur, cenas


def ruim_automatico(thumb):
    """Tela preta, cartela de texto ou quadro chapado: não serve como imagem de fundo."""
    from PIL import Image, ImageStat
    im = Image.open(thumb).convert("L")
    st = ImageStat.Stat(im)
    escuro = sum(im.histogram()[:28]) / (im.width * im.height)
    # bem conservador: gameplay noturno é escuro mas útil; só descarta tela praticamente preta/chapada
    return st.mean[0] < 12 or st.stddev[0] < 8 or escuro > 0.96


def folhas(thumbs, rotulos, destino_base, por_folha=30, colunas=6):
    from PIL import Image, ImageDraw, ImageFont
    fonte = ImageFont.truetype(str(FONTES / "Bangers-Regular.ttf"), 26)
    saidas = []
    for k in range(0, len(thumbs), por_folha):
        lote = list(zip(thumbs[k:k + por_folha], rotulos[k:k + por_folha]))
        w0, h0 = Image.open(lote[0][0]).size
        tw, th = (320, 180) if w0 >= h0 else (200, 356)
        if w0 < h0:
            colunas = 8
        linhas = (len(lote) + colunas - 1) // colunas
        folha = Image.new("RGB", (colunas * tw, linhas * (th + 34)), "black")
        d = ImageDraw.Draw(folha)
        for i, (t, rot) in enumerate(lote):
            im = Image.open(t).convert("RGB")
            im.thumbnail((tw, th))
            x, y = (i % colunas) * tw, (i // colunas) * (th + 34)
            folha.paste(im, (x + (tw - im.width) // 2, y))
            d.text((x + 6, y + th + 2), rot, font=fonte, fill="yellow")
        p = Path(f"{destino_base}_folha_{k // por_folha + 1}.jpg")
        folha.save(p, quality=85)
        saidas.append(p)
    return saidas


def indexar(pasta, lib_path):
    lib_path = Path(lib_path).resolve()
    base = lib_path.parent
    lib = ler_json(lib_path) if lib_path.exists() else {"videos": []}
    ja = {v["arquivo"] for v in lib["videos"]}
    mini = base / "miniaturas"; mini.mkdir(parents=True, exist_ok=True)
    for video in sorted(Path(pasta).resolve().rglob("*")):
        if video.suffix.lower() not in EXTS:
            continue
        try:
            rel = video.relative_to(base).as_posix()
        except ValueError:
            rel = str(video)
        if rel in ja:
            continue
        print("indexando", video.name, flush=True)
        dur, cenas = cenas_de(video)
        base_id = re.sub(r"\s*[\[(][A-Za-z0-9_-]{6,}[\])]\s*$", "", video.stem)   # tira o [id] do YouTube
        base_id = re.sub(r"[^A-Za-z0-9]+", "_", base_id).strip("_")
        base_id = re.sub(r"^Grand_Theft_Auto_(VI|6)(_|$)", r"GTA6\2", base_id, flags=re.I)
        base_id = base_id[:32].strip("_") or "video"
        vid, k = base_id, 2
        while any(v["id"] == vid for v in lib["videos"]):
            vid, k = f"{base_id}_{k}", k + 1
        regs, thumbs, rotulos = [], [], []
        for i, (a, b) in enumerate(cenas):
            t = mini / f"{vid}_{i:03d}.jpg"
            rodar([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{(a + b) / 2:.2f}", "-i", str(video),
                   "-frames:v", "1", "-vf", "scale=320:-2", str(t)])
            cid = f"{vid}#{i}"
            ruim = ruim_automatico(t)
            regs.append({"id": cid, "inicio": a, "fim": b, "thumb": t.relative_to(base).as_posix(),
                         "descricao": "auto: escura/vazia" if ruim else "", "tags": ["ruim"] if ruim else []})
            thumbs.append(t); rotulos.append(f"{i}  {int(a // 60)}:{a % 60:04.1f}" + ("  X" if ruim else ""))
        fl = folhas(thumbs, rotulos, mini / vid)
        lib["videos"].append({"arquivo": rel, "id": vid, "duracao": round(dur, 2),
                              "origem": "", "folhas": [f.relative_to(base).as_posix() for f in fl],
                              "cenas": regs})
        salvar_json(lib_path, lib)
        print(f"  {len(regs)} cenas, folhas: {', '.join(f.name for f in fl)}")
    salvar_json(lib_path, lib)


def pendentes(lib_path):
    lib = ler_json(lib_path)
    tot = 0
    for v in lib["videos"]:
        n = sum(1 for c in v["cenas"] if not c["tags"])
        tot += n
        if n:
            print(f"{v['id']}: {n}/{len(v['cenas'])} cenas sem tags -> {', '.join(v['folhas'])}")
    print(f"total sem tags: {tot}")


def marcar(lib_path, arquivo):
    lib = ler_json(lib_path)
    novos = ler_json(arquivo)
    cenas = {c["id"]: c for v in lib["videos"] for c in v["cenas"]}
    faltam = [k for k in novos if k not in cenas]
    for cid, val in novos.items():
        if cid not in cenas:
            continue
        c = cenas[cid]
        if val == "ruim":
            c["tags"], c["descricao"] = ["ruim"], c["descricao"] or "descartada"
        elif isinstance(val, list):
            c["descricao"], c["tags"] = val[0], [t.lower() for t in val[1]]
        else:
            c["descricao"] = val.get("d", c["descricao"])
            c["tags"] = [t.lower() for t in val.get("t", c["tags"])]
            if "foco" in val:
                c["foco"] = val["foco"]
    salvar_json(lib_path, lib)
    print(f"{len(novos) - len(faltam)} cenas atualizadas" + (f"; ids desconhecidos: {faltam}" if faltam else ""))


def pontuar(cena, termos):
    tags = {normalizar(w) for t in cena["tags"] for w in [t] + t.split()}   # "vista aerea" casa com "vista" e "aerea"
    alvo = tags | {normalizar(t) for t in cena["descricao"].split()}
    alvo.discard("")
    return sum(2 if t in tags else 1 for t in termos if t in alvo)


def uso_recente(lib_path, n=10, excluir=None):
    """{id da cena: nº de vezes} nos últimos n vídeos (pastas de videos/ ao lado de biblioteca/), para variar as cenas."""
    videos = Path(lib_path).resolve().parent.parent / "videos"
    uso = {}
    if not videos.is_dir():
        return uso
    rots = [r for r in sorted(videos.glob("*/roteiro.json")) if not excluir or r.parent.resolve() != Path(excluir).resolve()]
    for r in rots[-n:]:
        try:
            rot = ler_json(r)
        except Exception:
            continue
        for s in rot.get("segmentos", []):
            for c in s.get("clipes", []):
                if c.get("cena"):
                    uso[c["cena"]] = uso.get(c["cena"], 0) + 1
    return uso


PENALIDADE_USO = 1.5        # cada uso recente vale -1,5 ponto: a cena só volta se casar bem melhor que as outras


def buscar(lib_path, consulta, n=8, excluir=(), uso=None):
    lib = ler_json(lib_path)
    termos = [normalizar(t) for t in consulta.split() if normalizar(t)]
    uso = uso or {}
    res = []
    for v in lib["videos"]:
        for c in v["cenas"]:
            if c["id"] in excluir or "ruim" in c["tags"]:
                continue
            s = pontuar(c, termos)
            if s:
                res.append((s - PENALIDADE_USO * uso.get(c["id"], 0), c["fim"] - c["inicio"], v["arquivo"], c))
    res.sort(key=lambda r: (-r[0], -r[1]))
    return res[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["indexar", "pendentes", "buscar", "marcar"])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--lib", default="biblioteca/biblioteca.json")
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    if a.acao == "indexar":
        indexar(a.alvo, a.lib)
    elif a.acao == "pendentes":
        pendentes(a.lib)
    elif a.acao == "marcar":
        marcar(a.lib, a.alvo)
    else:
        uso = uso_recente(a.lib)
        for s, d, arq, c in buscar(a.lib, a.alvo or "", a.n, uso=uso):
            print(f"[{s:g}]{' (usada ' + str(uso[c['id']]) + 'x)' if uso.get(c['id']) else ''} {c['id']}  {c['inicio']:.1f}-{c['fim']:.1f}s ({d:.1f}s)  {c['descricao']}  {c['tags']}")


if __name__ == "__main__":
    main()
