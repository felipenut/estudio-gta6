"""Agendamento no Zernio (https://zernio.com/api/v1).

Uso:
  python zernio.py contas
  python zernio.py agendar --projetos a,b,c --inicio 2026-11-19T08:00 --intervalo 4
  python zernio.py conferir
  python zernio.py resultados        # views/curtidas de cada post publicado -> videos/_resultados.json

A chave e as contas escolhidas ficam em ferramentas/zernio.json (só no PC; não compartilhe esse arquivo).
Cada projeto agendado ganha videos/<projeto>/out/zernio.json com o id do post e o horário.
"""
import argparse, datetime, json, mimetypes, os, sys, time, urllib.error, urllib.request, uuid
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
RAIZ = FERR.parent
VIDEOS = RAIZ / "videos"
CONFIG = FERR / "zernio.json"
BASE = os.environ.get("ZERNIO_BASE", "https://zernio.com/api/v1")
FUSO = "America/Bahia"


class ErroZernio(Exception):
    pass


def config():
    try:
        c = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        c = {}
    c.setdefault("api_key", ""); c.setdefault("contas", []); c.setdefault("intervalo_h", 4); c.setdefault("fuso", FUSO)
    return c


def salvar_config(c):
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def _req(metodo, caminho, corpo=None, chave=None, tentativas=3, idempotencia=None):
    chave = chave or config()["api_key"]
    if not chave:
        raise ErroZernio("cole a chave da API do Zernio na tela Agendar")
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cabecalhos = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json",
                  "Accept": "application/json", "User-Agent": "estudio-gta6"}
    if idempotencia:
        cabecalhos["Idempotency-Key"] = idempotencia
    for t in range(tentativas):
        rq = urllib.request.Request(BASE + caminho, data=dados, method=metodo, headers=cabecalhos)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                txt = r.read().decode("utf-8", "replace")
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and t < tentativas - 1:
                time.sleep(3 * (t + 1)); continue
            if e.code in (401, 403):
                raise ErroZernio(f"chave do Zernio recusada (HTTP {e.code}). Confira a chave. {msg}")
            raise ErroZernio(f"HTTP {e.code} em {caminho}: {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if t < tentativas - 1:
                time.sleep(3); continue
            aviso = ". Confira no painel antes de reenviar" if idempotencia else ""
            raise ErroZernio(f"sem resposta do Zernio: {e}{aviso}") from e


def contas(chave=None):
    j = _req("GET", "/accounts", chave=chave)
    return [{"id": a.get("_id"), "plataforma": a.get("platform"), "usuario": a.get("username") or a.get("displayName") or "",
             "ativa": a.get("isActive", True)} for a in j.get("accounts", [])]


def enviar_arquivo(caminho, nome=None):
    """presign -> PUT -> publicUrl. 'nome' = nome limpo (sem espaço/acento) para o arquivo no Zernio."""
    import re, unicodedata
    caminho = Path(caminho)
    tipo = mimetypes.guess_type(caminho.name)[0] or ("video/mp4" if caminho.suffix == ".mp4" else "image/jpeg")
    nome = unicodedata.normalize("NFKD", nome or caminho.name).encode("ascii", "ignore").decode()
    nome = re.sub(r"[^A-Za-z0-9._-]+", "-", nome).strip("-") or ("video" + caminho.suffix)
    j = _req("POST", "/media/presign", {"filename": nome, "contentType": tipo})
    url_up, url_pub = j.get("uploadUrl"), j.get("publicUrl")
    if not url_up or not url_pub:
        raise ErroZernio(f"resposta inesperada do presign: {json.dumps(j)[:300]}")
    tam = caminho.stat().st_size
    for t in range(3):
        with open(caminho, "rb") as f:
            rq = urllib.request.Request(url_up, data=f, method="PUT",
                                        headers={"Content-Type": tipo, "Content-Length": str(tam)})
            try:
                with urllib.request.urlopen(rq, timeout=900) as r:
                    r.read()
                return url_pub
            except Exception as e:
                if t == 2:
                    raise ErroZernio(f"falha ao enviar {caminho.name}: {e}")
                time.sleep(5)


def video_final(p):
    out = p / "out"
    if (out / "final.mp4").exists():
        return out / "final.mp4"
    for f in sorted(out.glob("*.mp4")) if out.exists() else []:
        if f.name != "video_mudo.mp4" and not f.name.endswith((".parcial.mp4", "_tmp.mp4")):
            return f
    return None


def montar_post(p, quando, cfg, url_video, url_capa):
    rot = json.loads((p / "roteiro.json").read_text(encoding="utf-8"))
    post_txt = (p / "post.txt").read_text(encoding="utf-8").strip() if (p / "post.txt").exists() else ""
    legenda = post_txt or rot.get("titulo", "")
    titulo = (rot.get("titulo") or legenda)[:100]
    midia = {"type": "video", "url": url_video}
    if url_capa:
        midia["thumbnail"] = url_capa              # YouTube (capa personalizada)
        midia["instagramThumbnail"] = url_capa     # capa do Reels
    plats = []
    for c in cfg["contas"]:
        e = {"platform": c["plataforma"], "accountId": c["id"]}
        if c["plataforma"] == "tiktok":
            e["platformSpecificData"] = {"privacy_level": "PUBLIC_TO_EVERYONE", "allow_comment": True, "allow_duet": True,
                                         "allow_stitch": True, "content_preview_confirmed": True,
                                         "express_consent_given": True}
        elif c["plataforma"] == "youtube":
            e["platformSpecificData"] = {"title": titulo, "visibility": "public", "madeForKids": False}
        plats.append(e)
    corpo = {"content": legenda, "title": titulo, "mediaItems": [midia], "platforms": plats,
             "scheduledFor": quando.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": cfg.get("fuso", FUSO)}
    if any(c["plataforma"] == "youtube" for c in cfg["contas"]):
        corpo["visibility"] = "public"
    return corpo


HORARIOS_DIARIOS = tuple(datetime.time(8 + (i * 90) // 60, (i * 90) % 60) for i in range(10))


def agora_no_fuso(fuso):
    try:
        zona = ZoneInfo(fuso)
    except ZoneInfoNotFoundError:
        if fuso in ("America/Bahia", "America/Sao_Paulo"):
            zona = datetime.timezone(datetime.timedelta(hours=-3))
        else:
            return datetime.datetime.now()
    return datetime.datetime.now(zona).replace(tzinfo=None)


def planejar_diario(quantidade, inicio, existentes):
    """Preenche horários livres, com no máximo 10 vídeos por data no calendário local."""
    ocupados = {h.replace(second=0, microsecond=0) for h in existentes}
    por_dia = Counter(h.date() for h in existentes)
    dia = inicio.date()
    horarios = []
    while len(horarios) < quantidade:
        for hora in HORARIOS_DIARIOS:
            candidato = datetime.datetime.combine(dia, hora)
            if candidato < inicio or candidato in ocupados or por_dia[dia] >= len(HORARIOS_DIARIOS):
                continue
            horarios.append(candidato)
            por_dia[dia] += 1
            if len(horarios) == quantidade:
                return horarios
        dia += datetime.timedelta(days=1)
    return horarios


def agendar(projetos, inicio, intervalo_h, horarios=None):
    cfg = config()
    if not cfg["contas"]:
        raise ErroZernio("escolha pelo menos uma conta na tela Agendar")
    quando = inicio
    if horarios is not None and len(horarios) != len(projetos):
        raise ErroZernio("cada vídeo do lote precisa de um horário")
    erros = 0
    for i, nome in enumerate(projetos, 1):
        if horarios is not None:
            quando = horarios[i - 1]
        p = VIDEOS / nome
        reg = p / "out" / "zernio.json"
        if reg.exists():
            print(f"pulando {nome}: já agendado"); continue
        v = video_final(p)
        if not v:
            print(f"ERRO {nome}: sem vídeo pronto"); erros += 1; continue
        if horarios is not None and quando < agora_no_fuso(cfg["fuso"]) + datetime.timedelta(minutes=1):
            print(f"ERRO {nome}: o horário do lote passou durante o envio. Escolha uma nova data.", flush=True)
            erros += 1
            continue
        try:
            print(f"({i}/{len(projetos)}) [{quando:%d/%m %H:%M}] {nome}: enviando {v.name} ({v.stat().st_size / 1e6:.0f} MB)...", flush=True)
            url_v = enviar_arquivo(v, f"{nome}.mp4")
            capa = p / "out" / "capa.jpg"
            url_c = enviar_arquivo(capa, f"{nome}-capa.jpg") if capa.exists() else None
            if horarios is not None and quando <= agora_no_fuso(cfg["fuso"]):
                raise ErroZernio("o horário selecionado passou durante o upload; escolha um novo horário")
            corpo = montar_post(p, quando, cfg, url_v, url_c)
            j = _req("POST", "/posts", corpo, idempotencia=str(uuid.uuid4()))
            post = j.get("post", j)
            if not post.get("_id"):
                raise ErroZernio("o Zernio não confirmou o agendamento; confira no painel antes de reenviar")
            reg.write_text(json.dumps({"post_id": post.get("_id"), "status": post.get("status"),
                                       "horario": quando.strftime("%Y-%m-%dT%H:%M"), "fuso": cfg.get("fuso", FUSO),
                                       "contas": [f"{c['plataforma']}:{c['usuario']}" for c in cfg["contas"]],
                                       "enviado_em": datetime.datetime.now().isoformat(timespec="seconds")},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            if post.get("status") not in ("scheduled", "published"):
                (p / "status.txt").write_text("ATENÇÃO: conferir envio no Zernio", encoding="utf-8")
                raise ErroZernio(f"post {post['_id']} recebido sem confirmação de agendamento; confira no Zernio")
            (p / "status.txt").write_text(f"AGENDADO {quando:%d/%m %H:%M}", encoding="utf-8")
            print(f"   ok: post {post.get('_id')} ({post.get('status')})", flush=True)
            quando += datetime.timedelta(hours=intervalo_h)
        except ErroZernio as e:
            print(f"ERRO {nome}: {e}", flush=True); erros += 1
            if "recusada" in str(e):
                break
    return erros


def cancelar(nome):
    """Apaga o post no Zernio e libera o projeto para agendar de novo (guarda o horário em zernio_cancelado.json)."""
    p = VIDEOS / nome
    reg_p = p / "out" / "zernio.json"
    if not reg_p.is_file():
        raise ErroZernio("este vídeo não está agendado")
    reg = json.loads(reg_p.read_text(encoding="utf-8"))
    try:
        _req("DELETE", f"/posts/{reg.get('post_id')}")
    except ErroZernio as e:
        if "HTTP 404" not in str(e):
            raise
    reg["cancelado_em"] = datetime.datetime.now().isoformat(timespec="seconds")
    (p / "out" / "zernio_cancelado.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    reg_p.unlink()
    (p / "status.txt").write_text("PRONTO (agendamento cancelado)", encoding="utf-8")
    return reg


def conferir():
    """Consulta cada post agendado e atualiza out/zernio.json e o status do projeto.
    Post apagado no Zernio (404) -> desmarca, para poder agendar de novo."""
    probs = 0
    for p in sorted(VIDEOS.iterdir()):
        reg_p = p / "out" / "zernio.json"
        if not reg_p.is_file():
            continue
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        pid = reg.get("post_id")
        try:
            j = _req("GET", f"/posts/{pid}")
        except ErroZernio as e:
            if "HTTP 404" in str(e):
                reg_p.unlink()
                (p / "status.txt").write_text("PRONTO (agendamento sumiu do Zernio)", encoding="utf-8")
                print(f"NÃO EXISTE MAIS  {p.name}  (post {pid}): desmarcado, pode agendar de novo"); probs += 1
                continue
            print(f"ERRO ao consultar {p.name}: {e}"); probs += 1
            continue
        post = j.get("post", j)
        st = post.get("status", "?")
        plats = post.get("platforms") or []
        det = []
        for pl in plats:
            msg = pl.get("errorMessage") or pl.get("error") or ""
            det.append(f"{pl.get('platform')}={pl.get('status')}" + (f" ({msg})" if msg else ""))
        reg.update(status=st, plataformas=det, conferido_em=datetime.datetime.now().isoformat(timespec="seconds"))
        reg_p.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        h = reg.get("horario", "")[5:16].replace("T", " ")
        falhou = st in ("failed", "partial") or any("failed" in d or "error" in d for d in det)
        if st == "published" and not falhou:
            (p / "status.txt").write_text("PUBLICADO", encoding="utf-8")
            (p / "postado.txt").write_text(datetime.datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        elif falhou:
            (p / "status.txt").write_text(f"ERRO: Zernio {st} ({', '.join(det)})"[:200], encoding="utf-8"); probs += 1
            if st == "failed" and not any(pl.get("status") == "published" for pl in plats):
                reg_p.replace(p / "out" / "zernio_falhou.json")   # falha total permite reagendar
        elif st in ("draft",):
            (p / "status.txt").write_text(f"RASCUNHO no Zernio {h}", encoding="utf-8"); probs += 1
        print(f"{'OK  ' if not falhou and st != 'draft' else 'ATENÇÃO'} {h}  {p.name}: {st}  {' | '.join(det)}", flush=True)
    print(f"\n{probs} com problema" if probs else "\ntudo certo")
    return probs


METRICAS = ("views", "likes", "comments", "shares", "saves", "impressions", "reach")


def _num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def resultados():
    """Busca as métricas de cada post do Zernio (GET /analytics?postId=) e grava out/resultados.json em cada projeto
    e o resumo videos/_resultados.json. Precisa do Analytics no plano do Zernio (HTTP 402 = sem acesso)."""
    lista, n, pend = [], 0, 0
    regs = []
    for p in sorted(VIDEOS.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        reg = None
        for nome in ("zernio.json", "zernio_falhou.json"):
            f = p / "out" / nome
            if f.is_file():
                reg = json.loads(f.read_text(encoding="utf-8")); break
        if reg and reg.get("post_id"):
            regs.append((p, reg))
    total = len(regs)
    if not total:
        print("nenhum post do Zernio ainda (os números só existem para vídeos agendados pelo Estúdio)")
    for i, (p, reg) in enumerate(regs, 1):
        try:
            j = _req("GET", f"/analytics?postId={reg['post_id']}")
        except ErroZernio as e:
            if "HTTP 402" in str(e):
                print("ERRO: o seu plano do Zernio não inclui Analytics (HTTP 402). Ative o add-on de Analytics no Zernio.")
                return 1
            if "HTTP 404" in str(e) or "HTTP 424" in str(e):
                print(f"({i}/{total}) {p.name}: sem números (post não publicado ou apagado)"); continue
            print(f"({i}/{total}) {p.name}: ERRO {e}"); continue
        an = j.get("analytics") or {}
        plats = []
        for pl in j.get("platformAnalytics") or []:
            a = pl.get("analytics") or {}
            plats.append({"plataforma": pl.get("platform"), "url": pl.get("platformPostUrl"),
                          **{k: _num(a.get(k)) for k in METRICAS}})
        if j.get("syncStatus") == "pending":
            pend += 1
        rot = {}
        try:
            rot = json.loads((p / "roteiro.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        segs = rot.get("segmentos") or []
        item = {"nome": p.name, "titulo": rot.get("titulo", p.name), "serie": rot.get("serie", ""),
                "gancho": segs[0].get("texto", "") if segs else "", "publicado": j.get("publishedAt") or reg.get("horario"),
                **{k: _num(an.get(k)) for k in METRICAS}, "engajamento": float(an.get("engagementRate") or 0),
                "plataformas": plats, "sincronizado": j.get("syncStatus", ""),
                "atualizado": datetime.datetime.now().isoformat(timespec="seconds")}
        (p / "out" / "resultados.json").write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        lista.append(item); n += 1
        print(f"({i}/{total}) {p.name}: {item['views']} views, {item['likes']} curtidas, {item['comments']} coment.", flush=True)
    lista.sort(key=lambda x: -x["views"])
    resumo = {"atualizado": datetime.datetime.now().isoformat(timespec="seconds"), "videos": lista,
              "total": {k: sum(x[k] for x in lista) for k in METRICAS}}
    (VIDEOS / "_resultados.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{n} vídeo(s) com números" + (f" ({pend} ainda sincronizando no Zernio)" if pend else ""))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contas")
    sub.add_parser("conferir")
    sub.add_parser("resultados")
    a = sub.add_parser("agendar")
    a.add_argument("--projetos", required=True)
    a.add_argument("--inicio", required=True, help="AAAA-MM-DDTHH:MM no fuso configurado")
    a.add_argument("--intervalo", type=float, default=4)
    a.add_argument("--horarios", help="horários explícitos do lote, separados por vírgula")
    args = ap.parse_args()
    try:
        if args.cmd == "conferir":
            conferir(); return 0
        if args.cmd == "resultados":
            return resultados()
        if args.cmd == "contas":
            for c in contas():
                print(f"{c['plataforma']:10} {c['usuario']:25} {c['id']}")
            return 0
        ini = datetime.datetime.strptime(args.inicio[:16], "%Y-%m-%dT%H:%M")
        horarios = ([datetime.datetime.fromisoformat(h) for h in args.horarios.split(",")]
                    if args.horarios else None)
        return 1 if agendar([x for x in args.projetos.split(",") if x], ini, args.intervalo, horarios) else 0
    except ErroZernio as e:
        print(f"ERRO: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
