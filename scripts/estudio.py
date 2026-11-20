"""Estúdio GTA 6 Shorts v2: interface local no navegador para fazer o post inteiro sem sair dela.

  python ferramentas/scripts/estudio.py [--porta 8765] [--sem-navegador]

Abre http://127.0.0.1:8765 (só neste computador). Funções:
  - Novo vídeo: registra o pedido (tema/notas/fontes); o roteiro, as cenas e o post são escritos pelo Claude no chat;
  - Roteiro: editor com checador ao vivo, voz/velocidade com amostra;
  - Enquadramento e cenas: arrastar a janela 9:16, panorâmica, trocar a cena de um corte por miniatura;
  - Vídeo e post: player, capa (quadro + texto), música e volume, texto do post;
  - Biblioteca: baixar por link, vídeos oficiais, etiquetar à mão (ou pelo Claude no chat);
  - Temas: sugestões, IA sugere, histórico, perguntas dos fãs (Reddit), segredos e códigos; Configurações: chave e modelos;
  - Cortes e lives: achar momentos em lives/VODs, cortar vertical (reação com rosto em cima), modo ao vivo,
    lives agora, versões em outros idiomas; checagem antes do Zernio (motor adaptado do gtavi-claudecode, MIT).
Só executa etapas fixas do pipeline (nada de comando arbitrário). Só biblioteca padrão do Python.
"""
import argparse, datetime, json, mimetypes, os, re, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
RAIZ = FERR.parent                                # pasta skill-gta6
VIDEOS = RAIZ / "videos"
BIB = RAIZ / "biblioteca"
LIB = BIB / "biblioteca.json"
MUSICAS = RAIZ / "musicas"
sys.path.insert(0, str(AQUI))
import cortes as CT  # noqa: E402  (tela Cortes e lives)
import atualizar as ATU  # noqa: E402  (atualização automática pelo GitHub)

VERSAO = 21


def _versao_txt():
    try:
        return (FERR / "VERSAO.txt").read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


VERSAO_INICIO = _versao_txt()          # se mudar enquanto o programa roda, a tela avisa "atualização disponível"
TRABALHO = {"id": 0, "projeto": None, "acao": None, "rotulo": None, "log": None, "inicio": None, "fim": None,
            "codigo": None, "resultado": None, "progresso": 0.0, "etapa": "", "corte": None,
            "cancelando": False, "cancelado": False, "repetivel": False}
TRAVA = threading.Lock()
TRAVA_PROCESSO = threading.Lock()
PROCESSO_ATUAL = None
REPETIR = None
SEM_JANELA = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}   # sem piscar console no Windows
PORTA = 8765
VOZES = [("pt-BR-AntonioNeural", "Antonio (masculina)"), ("pt-BR-FranciscaNeural", "Francisca (feminina)"),
         ("pt-BR-ThalitaMultilingualNeural", "Thalita (feminina, multilíngue)"),
         ("pt-BR-MacerioMultilingualNeural", "Macerio (masculina, multilíngue)")]


# ---------------------------------------------------------------- utilidades
def ler(p, padrao=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return padrao


def gravar(p, dados):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def projeto_dir(nome, exigir_roteiro=True):
    p = (VIDEOS / nome).resolve()
    if p.parent != VIDEOS.resolve() or not p.is_dir() or (exigir_roteiro and not (p / "roteiro.json").exists()):
        raise FileNotFoundError(nome)
    return p


def status_de(p):
    s = p / "status.txt"
    if (p / "postado.txt").exists():
        return "POSTADO"
    return s.read_text(encoding="utf-8", errors="replace").strip() if s.exists() else ""


def video_final(p):
    """O vídeo pronto: out/final.mp4 ou qualquer .mp4 renomeado em out/ (menos os intermediários)."""
    out = p / "out"
    if not out.exists():
        return None
    if (out / "final.mp4").exists():
        return out / "final.mp4"
    for f in sorted(out.glob("*.mp4")):
        if f.name != "video_mudo.mp4" and not f.name.endswith((".parcial.mp4", "_tmp.mp4")):
            return f
    return None


def ocupado():
    return TRABALHO["acao"] is not None and TRABALHO["fim"] is None


def _encerrar_processo(proc):
    if not proc or proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, **SEM_JANELA)
    else:
        proc.terminate()


def cancelar_trabalho():
    """Interrompe a etapa local atual; lotes param após o vídeo atual e envios ao Zernio terminam com segurança."""
    with TRAVA:
        if not ocupado():
            raise ValueError("não há trabalho rodando")
        acao = TRABALHO["acao"]
        if acao == "zernio":
            raise ValueError("o envio ao Zernio não pode ser interrompido com segurança; confira o status no Zernio")
        if acao == "lote":
            if TRABALHO.get("rotulo") == "LOTE → ZERNIO":
                raise ValueError("o lote já está enviando vídeos ao Zernio; confira o status no Zernio")
            LOTE["parar"] = True
            return {"ok": True, "depois": "do vídeo atual"}
        TRABALHO["cancelando"] = True
    with TRAVA_PROCESSO:
        proc = PROCESSO_ATUAL
    _encerrar_processo(proc)
    return {"ok": True}


def repetir_trabalho():
    """Repete o último trabalho local elegível, usando os mesmos parâmetros."""
    with TRAVA:
        if ocupado():
            raise ValueError("espere o trabalho atual terminar")
        if not TRABALHO.get("repetivel") or not REPETIR:
            raise ValueError("este trabalho não pode ser repetido automaticamente")
        args = REPETIR
    iniciar(**args)
    return {"ok": True, "trabalho": TRABALHO}


# ---------------------------------------------------------------- trabalhos (etapas fixas do pipeline)
def etapas_projeto(acao, p):
    rot, out, lib = str(p / "roteiro.json"), str(p / "out"), str(LIB)
    E = {
        "checar": [["checar_roteiro.py", rot, "--lib", lib]],
        "previa": [["checar_roteiro.py", rot, "--lib", lib], ["narrar.py", rot, "--saida", out],
                   ["montar.py", rot, "--saida", out, "--lib", lib, "--so-plano"]],
        "gerar": [["checar_roteiro.py", rot, "--lib", lib], ["narrar.py", rot, "--saida", out],
                  ["montar.py", rot, "--saida", out, "--lib", lib], ["exportar_ae.py", out + "/timeline.json"]],
        "narrar": [["narrar.py", rot, "--saida", out, "--forcar"]],
        "capa": [["montar.py", rot, "--saida", out, "--so-capa"]],
        "ae": [["exportar_ae.py", out + "/timeline.json"]],
    }
    return E[acao]


ROTULOS = {"checar": "CHECAGEM", "previa": "PRÉVIA", "gerar": "VÍDEO", "narrar": "NARRAÇÃO", "capa": "CAPA",
           "ae": "AFTER EFFECTS", "criar": "CRIAÇÃO", "criar_gerar": "CRIAÇÃO + VÍDEO", "baixar": "DOWNLOAD",
           "oficiais": "VÍDEOS OFICIAIS", "lote": "LOTE", "zernio": "AGENDAMENTO", "tendencias": "TENDÊNCIAS", "etiquetar": "ETIQUETAS (IA)", "indexar": "INDEXAÇÃO",
           "momentos": "MOMENTOS", "cortar": "CORTE", "traduzir_clipe": "TRADUÇÃO DO CLIPE", "lives": "LIVES AGORA",
           "perguntas": "PERGUNTAS DOS FÃS", "traduzir_video": "VERSÃO TRADUZIDA"}


PESOS = {"checar_roteiro.py": 0.3, "narrar.py": 1.5, "montar.py": 10, "exportar_ae.py": 0.5, "zernio.py": 10,
         "baixar.py": 8, "biblioteca.py": 4, "tendencias.py": 1, "clipes/moments.py": 10, "clipes/secrets_map.py": 0.2,
         "clipes/cut.py": 5, "clipes/traduzir.py": 6, "clipes/streams.py": 1, "clipes/perguntas.py": 1,
         "traduzir_roteiro.py": 1}
NOMES = {"checar_roteiro.py": "checando roteiro", "narrar.py": "narração", "montar.py": "montando vídeo",
         "exportar_ae.py": "After Effects", "zernio.py": "enviando ao Zernio", "baixar.py": "baixando", "biblioteca.py": "indexando", "tendencias.py": "buscando no YouTube",
         "clipes/moments.py": "achando momentos", "clipes/secrets_map.py": "procurando segredos", "clipes/cut.py": "cortando",
         "clipes/traduzir.py": "traduzindo", "clipes/streams.py": "procurando lives", "clipes/perguntas.py": "lendo o Reddit",
         "traduzir_roteiro.py": "traduzindo o roteiro"}
RE_SUB = [(re.compile(r"corte (\d+)/(\d+)"), lambda m: 0.85 * int(m[1]) / int(m[2])),
          (re.compile(r"\((\d+)/(\d+)\)"), lambda m: (int(m[1]) - 0.5) / int(m[2])),
          (re.compile(r"\[download\]\s+([\d.]+)%"), lambda m: float(m[1]) / 100),
          (re.compile(r"^loudness:"), lambda m: 0.97), (re.compile(r"^ok: .*final\.mp4"), lambda m: 0.92)]


def _progresso(base, span, etapas, n, sub):
    """fração total = base + span * (peso das etapas feitas + sub * peso da atual) / peso total"""
    pesos = [PESOS.get(e[0], 1) for e in etapas]
    feito = sum(pesos[:n - 1]) + pesos[n - 1] * max(0.0, min(1.0, sub))
    TRABALHO["progresso"] = round(base + span * feito / (sum(pesos) or 1), 4)


def _executar(etapas, log, status, rotulo, base=0.0, span=1.0):
    global PROCESSO_ATUAL
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    codigo, saida_total = 0, []
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n===== {time.strftime('%H:%M:%S')} {rotulo} =====\n")
        for n, etapa in enumerate(etapas, 1):
            if TRABALHO.get("cancelando"):
                if status:
                    status.write_text("CANCELADO", encoding="utf-8")
                return 130, "".join(saida_total)
            if status:
                status.write_text(f"{n}-{etapa[0].replace('.py', '')}", encoding="utf-8")
            TRABALHO["etapa"] = f"{NOMES.get(etapa[0], etapa[0])} ({n}/{len(etapas)})" if len(etapas) > 1 else NOMES.get(etapa[0], etapa[0])
            _progresso(base, span, etapas, n, 0)
            f.write(f"$ {' '.join(etapa)}\n"); f.flush()
            proc = subprocess.Popen([sys.executable, str(AQUI / etapa[0])] + etapa[1:], cwd=str(RAIZ), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", **SEM_JANELA)
            with TRAVA_PROCESSO:
                PROCESSO_ATUAL = proc
                cancelar_agora = TRABALHO.get("cancelando")
            if cancelar_agora:
                _encerrar_processo(proc)
            try:
                for linha in proc.stdout:
                    f.write(linha); f.flush()
                    saida_total.append(linha)
                    for rx, fr in RE_SUB:
                        m = rx.search(linha)
                        if m:
                            try:
                                _progresso(base, span, etapas, n, fr(m))
                            except (ValueError, ZeroDivisionError):
                                pass
                            break
            finally:
                codigo = proc.wait()
                with TRAVA_PROCESSO:
                    if PROCESSO_ATUAL is proc:
                        PROCESSO_ATUAL = None
            if TRABALHO.get("cancelando"):
                if status:
                    status.write_text("CANCELADO", encoding="utf-8")
                return 130, "".join(saida_total)
            if codigo:
                if status:
                    status.write_text(f"ERRO: {etapa[0]} (veja o log)", encoding="utf-8")
                break
    return codigo, "".join(saida_total)


def iniciar(acao, etapas_fn, log, status=None, projeto=None, depois=None, corte=None):
    """etapas_fn(): lista de etapas (calculada na thread). depois(codigo, saida): encadeia mais trabalho."""
    global REPETIR
    with TRAVA:
        if ocupado():
            raise RuntimeError(f"já rodando: {TRABALHO['rotulo']} ({TRABALHO['projeto'] or 'biblioteca'})")
        TRABALHO.update(id=TRABALHO["id"] + 1, projeto=projeto, acao=acao, rotulo=ROTULOS.get(acao, acao),
                        log=str(log), inicio=time.time(), fim=None, codigo=None, resultado=None,
                        progresso=0.0, etapa="", corte=corte, cancelando=False, cancelado=False,
                        repetivel=acao not in ("zernio", "lote", "traduzir_video"))
        REPETIR = ({"acao": acao, "etapas_fn": etapas_fn, "log": log, "status": status, "projeto": projeto,
                    "depois": depois, "corte": corte} if TRABALHO["repetivel"] else None)

    def corre():
        codigo = 1
        try:
            codigo, saida = _executar(etapas_fn(), Path(log), status, ROTULOS.get(acao, acao))
            if depois and not TRABALHO.get("cancelando"):
                codigo = depois(codigo, saida) or codigo
            elif status and codigo == 0:
                status.write_text("PRÉVIA PRONTA" if acao == "previa" else "PRONTO", encoding="utf-8")
        except Exception as e:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"ERRO interno: {e}\n")
            if status:
                status.write_text(f"ERRO: {e}", encoding="utf-8")
        cancelado = bool(TRABALHO.get("cancelando"))
        if cancelado and status:
            status.write_text("CANCELADO", encoding="utf-8")
        TRABALHO.update(fim=time.time(), codigo=130 if cancelado else codigo, cancelado=cancelado, cancelando=False,
                        progresso=1.0 if codigo == 0 else TRABALHO["progresso"])

    threading.Thread(target=corre, daemon=True).start()


def acao_projeto(nome, acao):
    p = projeto_dir(nome)
    iniciar(acao, lambda: etapas_projeto(acao, p), p / "log.txt", p / "status.txt", nome)


# ---------------------------------------------------------------- gerar em lote
LOTE = {"ativo": False, "parar": False, "fila": [], "feitos": [], "erros": [], "atual": None, "agendar": False}


def fila_lote():
    """Projetos com roteiro e sem vídeo final, na ordem das datas."""
    if not VIDEOS.exists():
        return []
    return [d.name for d in sorted(VIDEOS.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "roteiro.json").exists()
            and not (d / "postado.txt").exists() and not video_final(d)]


def iniciar_lote(agendar=False):
    """agendar=True: ao terminar, manda os vídeos feitos para o Zernio (a partir do próximo horário livre)."""
    global REPETIR
    log = VIDEOS / "_lote_log.txt"
    if agendar:
        c = _zernio().config()
        if not c["api_key"] or not c["contas"]:
            raise ValueError("para agendar no fim do lote, configure a chave e as contas na tela Agendar")
    with TRAVA:
        if ocupado():
            raise RuntimeError(f"já rodando: {TRABALHO['rotulo']} ({TRABALHO['projeto'] or 'biblioteca'})")
        fila = fila_lote()
        if not fila:
            raise ValueError("nenhum projeto com roteiro e sem vídeo pronto")
        TRABALHO.update(id=TRABALHO["id"] + 1, projeto=fila[0], acao="lote", rotulo=f"LOTE 1/{len(fila)}",
                        log=str(VIDEOS / fila[0] / "log.txt"), inicio=time.time(), fim=None, codigo=None, resultado=None,
                        progresso=0.0, etapa="", cancelando=False, cancelado=False, repetivel=False)
        REPETIR = None
        LOTE.update(ativo=True, parar=False, fila=fila, feitos=[], erros=[], atual=fila[0], agendar=bool(agendar))

    def corre():
        n = len(fila)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%d/%m %H:%M')} LOTE com {n} vídeos =====\n")
        for i, nome in enumerate(fila, 1):
            if LOTE["parar"]:
                break
            p = VIDEOS / nome
            LOTE["atual"] = nome
            TRABALHO.update(projeto=nome, rotulo=f"LOTE {i}/{n}", log=str(p / "log.txt"))
            t0 = time.time()
            try:
                codigo, _ = _executar(etapas_projeto("gerar", p), p / "log.txt", p / "status.txt", f"VÍDEO (lote {i}/{n})",
                                      base=(i - 1) / n, span=1 / n)
            except Exception as e:
                codigo = 1
                (p / "status.txt").write_text(f"ERRO: {e}", encoding="utf-8")
            if codigo == 0:
                (p / "status.txt").write_text("PRONTO", encoding="utf-8")
                LOTE["feitos"].append(nome)
            else:
                LOTE["erros"].append(nome)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"{'OK  ' if codigo == 0 else 'ERRO'} {nome} ({time.time() - t0:.0f}s)\n")
        rotulo = f"LOTE {len(LOTE['feitos'])}/{n} prontos" + (" (parado)" if LOTE["parar"] else "")
        cod_z = 0
        if agendar and LOTE["feitos"]:
            ini = zernio_estado()["sugestao_inicio"]
            intervalo = _zernio().config()["intervalo_h"]
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"agendando {len(LOTE['feitos'])} no Zernio a partir de {ini}, a cada {intervalo}h\n")
            TRABALHO.update(projeto=None, rotulo="LOTE → ZERNIO", log=str(VIDEOS / "_zernio_log.txt"), progresso=0.0)
            try:
                cod_z, _ = _executar([["zernio.py", "agendar", "--projetos", ",".join(LOTE["feitos"]), "--inicio", ini,
                                       "--intervalo", str(intervalo)]], VIDEOS / "_zernio_log.txt", None, "AGENDAMENTO")
            except Exception as e:
                cod_z = 1
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"ERRO ao agendar: {e}\n")
            rotulo += " + agendados" if cod_z == 0 else " (agendamento com erro)"
        LOTE.update(ativo=False, atual=None)
        TRABALHO.update(fim=time.time(), codigo=0 if not LOTE["erros"] and not cod_z else 1, projeto=None,
                        log=str(VIDEOS / "_zernio_log.txt") if agendar and LOTE["feitos"] else str(log), progresso=1.0,
                        rotulo=rotulo)

    threading.Thread(target=corre, daemon=True).start()


# ---------------------------------------------------------------- revisão rápida
def aprovado(p):
    """Aprovado vale só para o vídeo que foi revisado (se gerar de novo, precisa revisar de novo)."""
    a, v = ler(Path(p) / "out" / "aprovado.json"), video_final(Path(p))
    return bool(a and v and abs(a.get("mtime", 0) - v.stat().st_mtime) < 2)


def revisao_lista(nome):
    p = projeto_dir(nome)
    tl, v = ler(p / "out" / "timeline.json"), video_final(p)
    if not tl or not v:
        raise ValueError("gere o vídeo primeiro")
    rot = ler(p / "roteiro.json") or {}
    segs = rot.get("segmentos", [])
    itens, visto = [], set()
    for i, c in enumerate(tl["cortes"]):
        sg = c.get("seg", 0)
        s = segs[sg] if sg < len(segs) else {}
        primeiro = sg not in visto
        visto.add(sg)
        itens.append({"i": i, "seg": sg, "t": round(c["t0"] + c["dur"] / 2, 2), "t0": c["t0"], "cena": c["cena"],
                      "texto": s.get("texto", "") if primeiro else "", "tipo": s.get("tipo", "") if primeiro else "",
                      "cartela": (s.get("cartela") if isinstance(s.get("cartela"), str) else (s.get("cartela") or {}).get("texto", "")) if primeiro else "",
                      "chave": primeiro and (sg == 0 or sg == len(segs) - 1 or bool(s.get("cartela")))})
    return {"itens": itens, "aprovado": aprovado(p), "mtime": v.stat().st_mtime}


def quadro_revisao(nome, i):
    p = projeto_dir(nome)
    v = video_final(p)
    it = revisao_lista(nome)["itens"][i]
    pasta = p / "out" / "revisao"; pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / f"{int(v.stat().st_mtime)}_{i:03d}.jpg"
    if not alvo.exists():
        for velho in pasta.glob("*.jpg"):
            if not velho.name.startswith(str(int(v.stat().st_mtime))):
                velho.unlink(missing_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{it['t']:.2f}", "-i", str(v), "-frames:v", "1",
                        "-vf", "scale=270:-2", "-q:v", "4", str(alvo)], check=True, **SEM_JANELA)
    return alvo


def aprovar(nome, valor=True):
    p = projeto_dir(nome)
    f = p / "out" / "aprovado.json"
    if valor:
        v = video_final(p)
        if not v:
            raise ValueError("gere o vídeo primeiro")
        gravar(f, {"mtime": v.stat().st_mtime, "em": datetime.datetime.now().isoformat(timespec="seconds")})
    elif f.exists():
        f.unlink()
    return aprovado(p)


# ---------------------------------------------------------------- resultados (Zernio Analytics)
def resultados():
    r = ler(VIDEOS / "_resultados.json", {"videos": [], "total": {}, "atualizado": None})
    vs = r.get("videos", [])
    def media(chave):
        g = {}
        for x in vs:
            k = x.get(chave) or ""
            if k:
                g.setdefault(k, []).append(x["views"])
        return sorted(({"nome": k, "videos": len(v), "media_views": round(sum(v) / len(v))} for k, v in g.items()),
                      key=lambda x: -x["media_views"])
    tipos = {}
    for x in vs:
        rot = ler(VIDEOS / x["nome"] / "roteiro.json") or {}
        segs = rot.get("segmentos") or []
        x["tema"] = rot.get("tema", "")
        x["dur_palavras"] = sum(len((sg.get("texto") or "").split()) for sg in segs)
    sem = [d.name for d in sorted(VIDEOS.iterdir()) if d.is_dir() and (d / "postado.txt").exists()
           and not (d / "out" / "resultados.json").exists()] if VIDEOS.exists() else []
    return {**r, "por_serie": media("serie"), "sem_numeros": sem,
            "media_views": round(sum(x["views"] for x in vs) / len(vs)) if vs else 0}


# ---------------------------------------------------------------- configuração inicial / ajustes
def em_onedrive():
    return "onedrive" in str(RAIZ).lower()


def config_estado():
    import skill_gerar, variacao
    c = ler(FERR / "primeira_config.json", {})
    z = _zernio().config()
    lib = ler(LIB, {"videos": []})
    skill = RAIZ / "skill" / skill_gerar.NOME / "SKILL.md"
    return {"concluida": bool(c.get("concluida")), "raiz": str(RAIZ), "onedrive": em_onedrive(),
            "skill": {"existe": skill.exists(), "caminho": str(skill), "zip": str(RAIZ / "skill" / f"{skill_gerar.NOME}.zip"),
                      "prompt": skill_gerar.prompt(), "enviada": bool(c.get("skill_enviada"))},
            "zernio": {"configurado": bool(z["api_key"]), "contas": len(z["contas"])},
            "biblioteca": {"videos": len(lib["videos"]), "cenas": sum(len(v["cenas"]) for v in lib["videos"]),
                           "status": status_de(BIB)},
            "variacao": variacao.config(), "vozes": VOZES,
            "versao": {"programa": VERSAO, "ferramentas": _versao_txt(), "inicio": VERSAO_INICIO}}


def config_salvar(corpo):
    c = ler(FERR / "primeira_config.json", {})
    for k in ("concluida", "skill_enviada"):
        if k in corpo:
            c[k] = bool(corpo[k])
    gravar(FERR / "primeira_config.json", c)
    return config_estado()


def gerar_skill():
    import skill_gerar
    return skill_gerar.gerar()


def abrir_no_explorer(caminho):
    alvo = Path(caminho)
    if not alvo.exists():
        raise FileNotFoundError(caminho)
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(alvo)] if alvo.is_file() else ["explorer", str(alvo)], **SEM_JANELA)
    return True


# ---------------------------------------------------------------- checagem antes de postar (rule-check)
def checagem_projeto(p):
    """Formato, áudio, duração, termos proibidos no post e crédito (clipes). Cache em out/checagem.json."""
    import hashlib
    v = video_final(p)
    if not v:
        return None
    rot = ler(p / "roteiro.json") or {}
    tipo = "clipe" if rot.get("tipo") == "clipe" else "narrado"
    canal = ((rot.get("fonte") or {}).get("canal") or "") if tipo == "clipe" else ""
    post = (p / "post.txt").read_text(encoding="utf-8", errors="replace") if (p / "post.txt").exists() else ""
    texto = "\n".join([post, rot.get("titulo", ""), rot.get("capa", "") if isinstance(rot.get("capa"), str) else ""])
    chave = f"{v.name}|{v.stat().st_mtime:.0f}|{hashlib.md5(texto.encode()).hexdigest()}|{tipo}"
    c = ler(p / "out" / "checagem.json")
    if c and c.get("chave") == chave:
        return c["resultado"]
    try:
        import checar
        meta = None
        if tipo == "clipe" and rot.get("corte"):
            meta = ler(CT.CORTES / str(rot["corte"].get("trabalho") or "-") / "edits" / f"clip_{rot['corte'].get('pick')}.json")
        r = checar.checar_video(v, texto, tipo, canal, meta)
    except BaseException as e:
        r = {"ok": False, "itens": [{"nome": "checagem", "ok": False, "nivel": "erro", "detalhe": str(e)[:200]}]}
    gravar(p / "out" / "checagem.json", {"chave": chave, "resultado": r})
    return r


# ---------------------------------------------------------------- Zernio (agendamento)
def _zernio():
    import zernio
    return zernio


def zernio_estado():
    z = _zernio(); c = z.config()
    prontos, agendados = [], []
    for d in sorted(VIDEOS.iterdir()) if VIDEOS.exists() else []:
        if not d.is_dir() or d.name.startswith((".", "_")) or not (d / "roteiro.json").exists():
            continue
        reg = ler(d / "out" / "zernio.json")
        titulo = (ler(d / "roteiro.json") or {}).get("titulo", d.name)
        if reg:
            agendados.append({"nome": d.name, "titulo": titulo, **reg})
        elif video_final(d) and not (d / "postado.txt").exists():
            prontos.append({"nome": d.name, "titulo": titulo, "aprovado": aprovado(d), "checagem": checagem_projeto(d),
                            "tipo": (ler(d / "roteiro.json") or {}).get("tipo") or "narrado"})
    agora = datetime.datetime.now()
    sug = (agora + datetime.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    if agendados:
        ult = max(datetime.datetime.strptime(a["horario"][:16], "%Y-%m-%dT%H:%M") for a in agendados if a.get("horario"))
        sug = max(sug, ult + datetime.timedelta(hours=float(c["intervalo_h"])))
    return {"configurado": bool(c["api_key"]),
            "contas": c["contas"], "intervalo_h": c["intervalo_h"], "fuso": c["fuso"],
            "prontos": prontos, "agendados": sorted(agendados, key=lambda a: a.get("horario", "")),
            "sugestao_inicio": sug.strftime("%Y-%m-%dT%H:%M")}


def zernio_config(corpo):
    z = _zernio(); c = z.config()
    if (corpo.get("api_key") or "").strip():
        c["api_key"] = corpo["api_key"].strip()
    if corpo.get("intervalo_h"):
        c["intervalo_h"] = max(0.5, float(corpo["intervalo_h"]))
    if isinstance(corpo.get("contas"), list):
        c["contas"] = [{"id": x["id"], "plataforma": x["plataforma"], "usuario": x.get("usuario", "")} for x in corpo["contas"]]
    z.salvar_config(c)
    return zernio_estado()


def zernio_agendar(corpo):
    projetos = [p for p in corpo.get("projetos", []) if (VIDEOS / p).is_dir()]
    if not projetos:
        raise ValueError("escolha pelo menos um vídeo pronto")
    barrados = []
    for nome in projetos:
        ch = checagem_projeto(projeto_dir(nome, False))
        if ch and not ch["ok"]:
            motivo = "; ".join(f"{i['nome']} ({i['detalhe']})" if i["detalhe"] else i["nome"] for i in ch["itens"] if i["nivel"] == "erro")
            barrados.append(f"{nome}: {motivo}")
    if barrados:
        raise ValueError("não passou na checagem antes de postar → " + " | ".join(barrados))
    ini = datetime.datetime.strptime(corpo["inicio"][:16], "%Y-%m-%dT%H:%M")
    if ini < datetime.datetime.now() + datetime.timedelta(minutes=10):
        raise ValueError("o primeiro horário precisa ser pelo menos 10 minutos no futuro")
    intervalo = float(corpo.get("intervalo_h") or _zernio().config()["intervalo_h"])
    etapa = ["zernio.py", "agendar", "--projetos", ",".join(projetos), "--inicio", ini.strftime("%Y-%m-%dT%H:%M"),
             "--intervalo", str(intervalo)]
    iniciar("zernio", lambda: [etapa], VIDEOS / "_zernio_log.txt", None, None)


def finalizar_corte(nome, pick, codigo):
    """Avalia e envia o clipe elegível na mesma fila."""
    if codigo:
        return codigo
    log = CT.trabalho_dir(nome) / "log.txt"
    def registrar(msg):
        with log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    try:
        TRABALHO.update(etapa="avaliando clipe", progresso=0.92)
        nota = CT.avaliar_clipe(nome, pick)
        registrar(f"Avaliação: {nota['nota']:.2f}/10. {nota['detalhes']}")
        if nota["nota"] <= 7.5 or not nota["checagem_ok"] or not nota["ia_ok"]:
            registrar("Agendamento automático não realizado: nota, checagem ou análise pendente.")
            return 0
        # Não repetir um envio nem sobrescrever um projeto já criado.
        for p in VIDEOS.iterdir() if VIDEOS.exists() else []:
            if not p.is_dir():
                continue
            r = ler(p / "roteiro.json") or {}
            c = r.get("corte") or {}
            if r.get("tipo") == "clipe" and c.get("trabalho") == nome and c.get("pick") == pick and not r.get("idioma"):
                registrar("Já existe um projeto para este clipe; confira em Agendar.")
                return 0
        estado = zernio_estado()
        if not estado["configurado"] or not estado["contas"]:
            registrar("Configure o Zernio e as contas antes de agendar automaticamente.")
            return 0
        if TRABALHO.get("cancelando"):
            return 130
        projeto = CT.para_projeto({"nome": nome, "pick": pick})
        ch = checagem_projeto(projeto_dir(projeto, False))
        if not ch or not ch.get("ok"):
            registrar("Projeto criado; a checagem impediu o agendamento automático.")
            return 0
        with TRAVA:
            if TRABALHO.get("cancelando"):
                registrar("Agendamento interrompido antes do envio.")
                return 130
            TRABALHO.update(acao="zernio", rotulo="AGENDAMENTO AUTOMÁTICO", etapa="enviando ao Zernio", projeto=projeto,
                            repetivel=False, progresso=0.0)
        etapas = [["zernio.py", "agendar", "--projetos", projeto, "--inicio", estado["sugestao_inicio"],
                   "--intervalo", str(estado["intervalo_h"])]]
        registrar(f"Clipe elegível: enviando {projeto} para o Zernio.")
        cod, _ = _executar(etapas, VIDEOS / "_zernio_log.txt", None, "AGENDAMENTO AUTOMÁTICO")
        registrar("Enviado ao Zernio." if cod == 0 else "Falha no envio; confira o status no Zernio antes de tentar novamente.")
        return cod
    except Exception as e:
        registrar(f"Avaliação ou agendamento não concluído: {type(e).__name__}: {e}")
        return 1


def atualizar_projeto_clipe(nome, pick, projeto, codigo):
    """Atualiza o projeto após renderizar, preservando o vídeo anterior."""
    if codigo:
        return codigo
    import shutil
    p = projeto_dir(projeto)
    rot = ler(p / "roteiro.json") or {}
    corte = rot.get("corte") or {}
    if rot.get("tipo") != "clipe" or corte.get("trabalho") != nome or corte.get("pick") != pick or rot.get("idioma"):
        raise ValueError("o projeto não corresponde a este clipe original")
    if ler(p / "out" / "zernio.json"):
        raise ValueError("o vídeo já foi agendado; cancele o agendamento antes de alterar")
    origem = CT.trabalho_dir(nome) / "edits" / f"clip_{pick}.mp4"
    alvo = p / "out" / "final.mp4"
    reserva = p / "backup"; reserva.mkdir(exist_ok=True)
    temporario = p / "out" / "final-atualizado.parcial.mp4"
    shutil.copy2(origem, temporario)
    if alvo.exists():
        shutil.copy2(alvo, reserva / f"final-antes-edicao-{time.time_ns()}.mp4")
    temporario.replace(alvo)
    (p / "status.txt").write_text("PRONTO", encoding="utf-8")
    TRABALHO["resultado"] = {"projeto_atualizado": p.name}
    return 0


def slug(txt, n=40):
    import unicodedata
    s = unicodedata.normalize("NFD", txt.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n].strip("-") or "video"


def criar_video(corpo):
    """Registra o pedido. Quem escreve o roteiro é o Claude, no chat (lê pedido.json e grava roteiro.json)."""
    tema = (corpo.get("tema") or "").strip()
    if len(tema) < 4:
        raise ValueError("escreva o tema do vídeo")
    data = corpo.get("data_post") or (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    nome = f"{data}_{slug(tema)}"
    k = 2
    while (VIDEOS / nome).exists():
        nome = f"{data}_{slug(tema)}-{k}"; k += 1
    p = VIDEOS / nome
    p.mkdir(parents=True)
    gravar(p / "pedido.json", {"tema": tema, "tema_catalogo": (corpo.get("tema_catalogo") or "").strip(), "data_post": data, "notas": (corpo.get("notas") or "").strip(),
                               "fontes": (corpo.get("fontes") or "").strip(),
                               "criado": datetime.datetime.now().isoformat(timespec="seconds")})
    (p / "status.txt").write_text(STATUS_PEDIDO, encoding="utf-8")
    return nome


STATUS_PEDIDO = "AGUARDANDO ROTEIRO (Claude)"


def acao_biblioteca(acao, corpo):
    log, st = BIB / "log.txt", BIB / "status.txt"
    vids = str(BIB / "videos")
    idx = ["biblioteca.py", "indexar", vids, "--lib", str(LIB)]
    if acao == "baixar":
        url = (corpo.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            raise ValueError("cole um link http(s) do vídeo")
        et = [["baixar.py", "baixar", url, "--pasta", vids] + (["--trecho", corpo["trecho"]] if corpo.get("trecho") else []), idx]
    elif acao == "oficiais":
        et = [["baixar.py", "oficiais", "--pasta", vids], idx]
    elif acao == "indexar":
        et = [idx]
    else:
        raise ValueError("ação inválida")
    iniciar(acao, lambda: et, log, st)


# ---------------------------------------------------------------- dados para a interface
def info_projeto(p):
    out = p / "out"
    arquivos = {n: (out / n).exists() for n in ("final.mp4", "capa.jpg", "previa_enquadramento.jpg", "projeto_ae.jsx",
                                                "legenda.srt", "narracao.mp3", "timeline.json")}
    tl = ler(out / "timeline.json")
    cortes = []
    if tl:
        for i, c in enumerate(tl["cortes"]):
            cortes.append({"i": i, "seg": c["seg"], "ref_idx": c.get("ref_idx", 0), "cena": c["cena"],
                           "layout": c["layout"], "foco": c["foco"], "motivo": c.get("motivo", ""),
                           "t0": c["t0"], "dur": c["dur"]})
    return {"nome": p.name, "roteiro": ler(p / "roteiro.json"), "pedido": ler(p / "pedido.json"), "status": status_de(p), "postado": (p / "postado.txt").exists(), "arquivos": arquivos,
            "video_pronto": bool(video_final(p)), "zernio": ler(p / "out" / "zernio.json"),
            "zernio_cancelado": ler(p / "out" / "zernio_cancelado.json"), "aprovado": aprovado(p),
            "resultados": ler(p / "out" / "resultados.json"),
            "mtimes": {n: (out / n).stat().st_mtime for n, ok in arquivos.items() if ok},
            "post": (p / "post.txt").read_text(encoding="utf-8") if (p / "post.txt").exists() else "",
            "checagem": checagem_projeto(p) if video_final(p) else None,
            "traducoes": sorted(x.name for x in VIDEOS.glob(p.name + "_*") if x.is_dir() and (x / "roteiro.json").exists()),
            "cortes": cortes, "total": tl.get("total") if tl else None, "trabalho": TRABALHO}


def lista_projetos():
    lista = []
    if VIDEOS.exists():
        for d in VIDEOS.iterdir():
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            rot = ler(d / "roteiro.json") or {}
            ped = ler(d / "pedido.json") or {}
            segs = rot.get("segmentos", [])
            chk = checagem_projeto(d) if rot.get("tipo") == "clipe" and video_final(d) else None
            lista.append({"nome": d.name, "titulo": rot.get("titulo", "") or ped.get("tema", "") or d.name, "status": status_de(d),
                          "tem_video": bool(video_final(d)), "postado": (d / "postado.txt").exists(), "mtime": d.stat().st_mtime,
                          "gancho": segs[0]["texto"] if segs else "", "cta": segs[-1]["texto"] if segs else "",
                          "data_post": rot.get("data_post", d.name[:10]), "tem_roteiro": bool(rot),
                          "aprovado": aprovado(d) if video_final(d) else False,
                          "agendado": bool(ler(d / "out" / "zernio.json")), "tipo": rot.get("tipo") or "narrado",
                          "checagem_ok": bool(chk and chk.get("ok")) if rot.get("tipo") == "clipe" else None})
    return sorted(lista, key=lambda x: -x["mtime"])


def quadro_do_corte(nome, idx):
    p = projeto_dir(nome)
    tl = ler(p / "out" / "timeline.json")
    c = tl["cortes"][idx]
    pasta = p / "out" / "quadros"; pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / (re.sub(r"[^\w.-]", "_", f"{Path(c['arquivo']).stem}_{c['src_in']:.2f}_{c['dur']:.2f}") + ".jpg")
    if not alvo.exists():
        import montar as M
        t = M.tarjas(c["arquivo"], c["src_in"], c["dur"])
        vf = (f"crop={t[0]}:{t[1]}:{t[2]}:{t[3]}," if t else "") + "scale=480:-2"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['src_in'] + c['dur'] / 2:.2f}", "-i", c["arquivo"],
                        "-frames:v", "1", "-vf", vf, "-q:v", "3", str(alvo)], check=True, **SEM_JANELA)
    return alvo


def clipe_do_corte(nome, idx):
    """Trecho curto (sem áudio, 480 px, sem tarjas) do corte, para tocar no cartão de enquadramento."""
    p = projeto_dir(nome)
    c = ler(p / "out" / "timeline.json")["cortes"][idx]
    pasta = p / "out" / "quadros"; pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / (re.sub(r"[^\w.-]", "_", f"{Path(c['arquivo']).stem}_{c['src_in']:.2f}_{c['dur']:.2f}") + ".mp4")
    if not alvo.exists():
        import montar as M
        t = M.tarjas(c["arquivo"], c["src_in"], c["dur"])
        vf = (f"crop={t[0]}:{t[1]}:{t[2]}:{t[3]}," if t else "") + "scale=480:-2"
        tmp = alvo.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['src_in']:.2f}", "-t", f"{c['dur']:.2f}", "-i", c["arquivo"],
                        "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(tmp)], check=True, **SEM_JANELA)
        tmp.replace(alvo)
    return alvo


def salvar_enquadramento(nome, idx, valor):
    p = projeto_dir(nome)
    rot = ler(p / "roteiro.json")
    enq = rot.setdefault("enquadramento", {})
    if valor in (None, "auto"):
        enq.pop(str(idx), None)
    else:
        enq[str(idx)] = valor
    gravar(p / "roteiro.json", rot)
    tl = ler(p / "out" / "timeline.json")
    if tl and 0 <= idx < len(tl["cortes"]) and valor not in (None, "auto"):
        c = tl["cortes"][idx]
        if isinstance(valor, str):
            c["layout"] = valor
        else:
            c["layout"], c["foco"] = "cheio", valor
        c["motivo"] = "manual"
        gravar(p / "out" / "timeline.json", tl)
    return enq


def trocar_cena(nome, idx, cena):
    """Troca a cena usada pelo corte idx (no roteiro: o clipe correspondente do segmento)."""
    p = projeto_dir(nome)
    rot = ler(p / "roteiro.json")
    tl = ler(p / "out" / "timeline.json")
    c = tl["cortes"][idx]
    seg = rot["segmentos"][c["seg"]]
    if not seg.get("clipes"):                       # segmento era automático: fixa as cenas atuais primeiro
        vistos = []
        for x in tl["cortes"]:
            if x["seg"] == c["seg"] and x["cena"] not in vistos:
                vistos.append(x["cena"])
        seg["clipes"] = [{"cena": v} for v in vistos]
    ri = min(c.get("ref_idx", 0), len(seg["clipes"]) - 1)
    seg["clipes"][ri] = {"cena": cena}
    rot.get("enquadramento", {}).pop(str(idx), None)
    gravar(p / "roteiro.json", rot)
    return seg["clipes"]


def checar_roteiro(rot):
    import io, contextlib
    from checar_roteiro import checar
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        erros, avisos = checar(rot, str(LIB))
    return {"resumo": buf.getvalue().strip(), "erros": erros, "avisos": avisos}


def temas_md():
    p = FERR / "references" / "temas.md"
    if not p.exists():
        return []
    out = []
    for linha in p.read_text(encoding="utf-8").splitlines():
        if linha.startswith("## Ganchos"):
            break
        m = re.match(r"^- (?:\*\*(.+?)\*\*[:\s]*)?(.+)$", linha.strip())
        if m:
            titulo = (m.group(1) or "").strip('" ')
            resto = re.sub(r"\*\*|`", "", m.group(2)).strip()
            out.append(titulo + (": " if titulo else "") + resto)
    usados = temas_usados()
    return [t for t in out if _norm(t) not in usados and _norm(re.sub(r"^[^:]{0,40}:\s*", "", t)) not in usados][:200]


def temas_series(n=10):
    """Combina fórmulas × assuntos de references/series.json, só o que ainda não virou projeto."""
    import random
    cfg = ler(FERR / "references" / "series.json") or {}
    usados = temas_usados()
    todos = [f["modelo"].replace("{x}", a) for f in cfg.get("formulas", []) for a in cfg.get("assuntos", {}).get(f["assuntos"], [])]
    livres = [t for t in todos if _norm(t) not in usados]
    random.shuffle(livres)
    # espalha entre as séries: no máximo 2 da mesma fórmula por sorteio
    escolha, por_serie = [], {}
    for t in livres:
        chave = t.split(":")[0]
        if por_serie.get(chave, 0) < 2:
            escolha.append(t); por_serie[chave] = por_serie.get(chave, 0) + 1
        if len(escolha) >= n:
            break
    return {"temas": escolha, "livres": len(livres), "total": len(todos)}


def tendencias():
    j = ler(VIDEOS / "_tendencias.json") or {}
    usados = temas_usados()
    for x in j.get("itens", []):
        x["usado"] = _norm(x.get("titulo", "")) in usados
    return j


def _norm(t):
    return slug(t or "")


def temas_usados():
    """Temas que já viraram projeto (pedido ou roteiro): saem do catálogo."""
    usados = set()
    if VIDEOS.exists():
        for d in VIDEOS.iterdir():
            if not d.is_dir():
                continue
            ped, rot = ler(d / "pedido.json") or {}, ler(d / "roteiro.json") or {}
            for t in (ped.get("tema_catalogo"), ped.get("tema"), rot.get("tema"), rot.get("titulo")):
                if t:
                    usados.add(_norm(t)); usados.add(_norm(re.sub(r"^[^:]{0,40}:\s*", "", t)))
    usados.discard("")
    return usados


# ---------------------------------------------------------------- modo copiar e colar (ChatGPT)
def prompt_chatgpt(nome):
    import criar
    p = projeto_dir(nome, False)
    ped = ler(p / "pedido.json") or {}
    if not ped.get("tema"):
        raise ValueError("este projeto não tem pedido.json com tema")
    import biblioteca as B
    _, txt = criar.lista_cenas(ler(LIB), B.uso_recente(LIB, 10, p))
    fontes = [{"titulo": u.strip(), "url": u.strip(), "texto": ""} for u in (ped.get("fontes") or "").split(",") if u.strip()]
    ganchos, ctas = criar.historico(excluir=p)
    msgs = criar.montar_prompt(ped["tema"], ped.get("data_post", nome[:10]), fontes, ped.get("notas", ""), txt, ganchos, ctas)
    return (msgs[0]["content"] + "\n\n" + msgs[1]["content"] + "\n\n" + REGRAS_RIGIDAS)


REGRAS_RIGIDAS = """=== REGRAS OBRIGATÓRIAS (o programa REJEITA o roteiro que quebrar qualquer uma) ===
PASSO 0 — PESQUISA: antes de escrever, pesquise na web notícias recentes e confiáveis sobre o tema. Nunca invente números, datas,
nomes de missões, personagens ou recursos. Sem fonte = não cite o número. Rumor = escreva "segundo rumores".

TAMANHO
R1. Total de 150 a 185 palavras somando todos os "texto" (conte!). Menos de 130 ou mais de 200 = rejeitado.
R2. 10 a 14 segmentos. Cada segmento no máximo 32 palavras (ideal 8–18). Nenhuma frase com mais de 24 palavras.

ESTRUTURA
R3. Segmento 1: "tipo": "gancho", no MÁXIMO 16 palavras, contém "GTA 6" e um fato forte. PROIBIDO começar com
    "Oi", "Olá", "E aí", "Fala galera", "Fala pessoal", "Hoje vou", "Neste vídeo".
R4. Segmento 2: "tipo": "promessa" (loop aberto: "fica até o final…").
R5. Um CTA leve no meio (tipo "cta", com salva/manda/compartilha) e o ÚLTIMO segmento "tipo": "cta" com uma PERGUNTA (com "?")
    e um verbo: comenta/segue/salva/manda.
R6. Pelo menos 2 micro-ganchos no texto, usando EXATAMENTE uma destas expressões: "mas", "só que", "o pior", "agora vem",
    "espera", "detalhe:", "isso não é nada", "e tem mais", "no final", "ninguém viu", "ninguém percebeu", "repara".
R7. Use pelo menos 4 tipos diferentes e pelo menos 1 "piada". No máximo 2 "duplo_sentido".
    Tipos permitidos (escreva exatamente assim, sem acento): gancho, promessa, historia, curiosidade, piada, duplo_sentido,
    comparacao, pergunta, cta, payoff.

TEXTO FALADO
R8. Escreva "GTA 6" e "GTA 5" com algarismos. NUNCA "GTA VI" ou "GTA V" no "texto" (a voz lê errado). Números em algarismos.
R9. Português falado do Brasil, frases curtas. Humor de TV aberta: nada sexual explícito, menores, assédio ou preconceito.

CAMPOS DE CADA SEGMENTO
R10. "destaque": lista com 1 ou 2 itens. CADA ITEM É UMA ÚNICA PALAVRA, SEM ESPAÇO, copiada IGUAL do "texto" daquele segmento.
     Errado: ["Los Santos"], ["ao vivo"], ["GTA 6"]. Certo: ["Santos"], ["vivo"], ["Leonida"].
R11. "cartela" (opcional, 3 a 5 no vídeo): texto CURTO em MAIÚSCULAS com o número/data forte (ex.: "212 GB", "19/11 - 00H").
     Sem "•". Use em pelo menos 1 segmento.
R12. "sfx" (opcional): só "impacto", "whoosh" ou "pop". "impacto" nas 2–3 revelações mais fortes.
R13. "clipes": OBRIGATÓRIO em todo segmento, mínimo 2 apelidos, cerca de 1 para cada 6 palavras. Só apelidos que existem na
     LISTA DE CENAS (numa faixa "G42 a G56" vale qualquer número dela, ex.: "G45"). Nunca repita um apelido no vídeo.
     Evite as marcadas "(usada)". Cena de logo/texto só no gancho. A cena precisa ilustrar o que a frase diz.
R14. Não invente campos. "imagem" só com os arquivos listados acima.

SAÍDA
R15. Responda SOMENTE com o JSON (sem ``` e sem texto antes ou depois), neste formato:
{"titulo": "até 60 caracteres", "capa": "ATÉ 7 PALAVRAS", "serie": "nome-da-serie ou vazio",
 "segmentos": [
  {"tipo": "gancho", "texto": "...", "destaque": ["palavra"], "sfx": "impacto", "clipes": ["A12", "C3"]},
  {"tipo": "promessa", "texto": "...", "destaque": ["palavra"], "cartela": "5 SEGREDOS", "clipes": ["B7", "B9"]}
 ],
 "post": "legenda curta com 1 pergunta + 6 a 8 hashtags (#gta6 #gtavi ...)",
 "fontes_usadas": [1]}

CHECAGEM FINAL (faça em silêncio antes de responder; se algo falhar, reescreva):
[ ] contei as palavras: entre 150 e 185      [ ] gancho ≤ 16 palavras, com "GTA 6", sem saudação
[ ] 2+ micro-ganchos da lista R6             [ ] último segmento é "cta" com "?"
[ ] todo "destaque" é 1 palavra que está no texto do próprio segmento
[ ] nenhum "GTA VI"/"GTA V" no texto        [ ] todo segmento tem 2+ clipes válidos, sem repetição
[ ] JSON válido, sem comentários"""


def prompt_correcao(nome):
    """Prompt para colar no ChatGPT e corrigir o roteiro atual (com os erros e avisos da checagem)."""
    p = projeto_dir(nome, False)
    rot = ler(p / "roteiro.json")
    if not rot:
        raise ValueError("este projeto ainda não tem roteiro")
    chk = checar_roteiro(rot)
    if not chk["erros"] and not chk["avisos"]:
        raise ValueError("o roteiro não tem erros nem avisos")
    probs = "\n".join([f"- ERRO: {e}" for e in chk["erros"]] + [f"- aviso: {a}" for a in chk["avisos"]])
    return ("Corrija este roteiro de vídeo curto sobre GTA 6. A checagem automática encontrou:\n" + probs +
            f"\n\nResumo atual: {chk['resumo']}\n\n" + REGRAS_RIGIDAS.split("SAÍDA")[0] +
            "\nIMPORTANTE NA CORREÇÃO:\n- Mude só o necessário para resolver TODOS os itens acima; mantenha o estilo e os fatos.\n"
            "- NÃO mexa nos \"clipes\" (são ids reais, ex.: \"TRAILER2#14\"); se apagar ou dividir um segmento, mantenha ou divida os clipes dele.\n"
            "- Responda SOMENTE com o JSON completo corrigido, no MESMO formato abaixo (com todos os campos), sem ``` e sem texto.\n\n"
            "ROTEIRO ATUAL:\n" + json.dumps(rot, ensure_ascii=False))


def colar_chatgpt(nome, texto):
    import criar, ia
    from checar_roteiro import checar
    p = projeto_dir(nome, False)
    ped = ler(p / "pedido.json") or {"data_post": nome[:10], "tema": (ler(p / "roteiro.json") or {}).get("tema", "")}
    try:
        resp = ia.extrair_json(texto or "")
    except Exception:
        raise ValueError("não achei o JSON na resposta colada (copie a resposta inteira do ChatGPT)")
    if not isinstance(resp, dict) or not resp.get("segmentos"):
        raise ValueError("o JSON colado não tem 'segmentos'")
    segs = resp["segmentos"]
    if all(isinstance(sg, dict) and isinstance(sg.get("clipes"), list) for sg in segs) and \
            any("#" in str(c.get("cena", "")) for sg in segs for c in sg["clipes"] if isinstance(c, dict)):
        # roteiro.json completo (formato do Claude): grava como está
        rot = resp
        post = rot.pop("post", "") if isinstance(rot.get("post"), str) else ""
        ids = {c["id"] for v in ler(LIB, {"videos": []})["videos"] for c in v["cenas"]}
        faltam = sorted({c.get("cena") for sg in segs for c in sg["clipes"] if c.get("cena") not in ids})
        for sg in segs:
            sg["clipes"] = [c for c in sg["clipes"] if c.get("cena") in ids]
        from checar_roteiro import consertar
        consertar(rot)
        criar.completar_cenas(rot, str(LIB), p)
        rot.setdefault("data_post", ped.get("data_post", nome[:10]))
        rot.setdefault("tema", ped.get("tema", ""))
        gravar(p / "roteiro.json", rot)
        if post.strip():
            (p / "post.txt").write_text(post.strip() + "\n", encoding="utf-8")
        (p / "status.txt").write_text("ROTEIRO PRONTO (colado)", encoding="utf-8")
        chk = checar_roteiro(rot)
        if faltam:
            chk["avisos"] = [f"{len(faltam)} cena(s) não existem nesta biblioteca e foram trocadas: {', '.join(faltam[:5])}"] + chk.get("avisos", [])
        return chk
    apelidos, _ = criar.lista_cenas(ler(LIB))
    fontes = [{"titulo": u.strip(), "url": u.strip()} for u in (ped.get("fontes") or "").split(",") if u.strip()]
    rot, problemas, post = criar.converter(resp, apelidos, fontes)
    from checar_roteiro import consertar
    consertar(rot)
    if isinstance(resp.get("serie"), str) and resp["serie"].strip():
        rot["serie"] = resp["serie"].strip()
    criar.completar_cenas(rot, str(LIB), p)
    rot["data_post"] = ped.get("data_post", nome[:10])
    rot["tema"] = ped.get("tema", "")
    gravar(p / "roteiro.json", rot)
    if post.strip():
        (p / "post.txt").write_text(post.strip() + "\n", encoding="utf-8")
    (p / "status.txt").write_text("ROTEIRO PRONTO (ChatGPT)", encoding="utf-8")
    chk = checar_roteiro(rot)
    chk["erros"] = problemas + chk["erros"]
    return chk


def biblioteca_resumo():
    lib = ler(LIB, {"videos": []})
    vids = []
    for v in lib["videos"]:
        cs = v["cenas"]
        vids.append({"id": v["id"], "arquivo": v["arquivo"], "duracao": v.get("duracao"), "cenas": len(cs),
                     "pendentes": sum(1 for c in cs if not c["tags"]), "ruins": sum(1 for c in cs if "ruim" in c["tags"])})
    import biblioteca as B
    uso = B.uso_recente(LIB, 10)
    boas = [c["id"] for v in lib["videos"] for c in v["cenas"] if c["tags"] and "ruim" not in c["tags"]]
    usadas = sum(1 for c in boas if uso.get(c))
    return {"videos": vids, "status": status_de(BIB), "trabalho": TRABALHO,
            "variedade": {"boas": len(boas), "usadas_recentes": usadas, "livres": len(boas) - usadas}}


def biblioteca_cenas(video=None, filtro="todas", q="", limite=300):
    lib = ler(LIB, {"videos": []})
    termos = [t for t in re.split(r"\s+", q.lower().strip()) if t]
    res = []
    if termos:
        import biblioteca as B
        for _, _, _, c in B.buscar(LIB, q, limite):
            res.append(c)
    else:
        for v in lib["videos"]:
            if video and v["id"] != video:
                continue
            for c in v["cenas"]:
                if filtro == "pendentes" and c["tags"]:
                    continue
                if filtro == "ruins" and "ruim" not in c["tags"]:
                    continue
                if filtro == "boas" and (not c["tags"] or "ruim" in c["tags"]):
                    continue
                res.append(c)
    return [{"id": c["id"], "inicio": c["inicio"], "fim": c["fim"], "descricao": c["descricao"], "tags": c["tags"],
             "thumb": "/bib/" + c["thumb"]} for c in res[:limite]]


def marcar_cena(cid, descricao=None, tags=None, ruim=None):
    lib = ler(LIB)
    for v in lib["videos"]:
        for c in v["cenas"]:
            if c["id"] == cid:
                if descricao is not None:
                    c["descricao"] = descricao.strip()[:160]
                if tags is not None:
                    c["tags"] = [t.strip().lower() for t in tags if t.strip()][:10]
                if ruim is True:
                    c["tags"] = ["ruim"]
                elif ruim is False and c["tags"] == ["ruim"]:
                    c["tags"] = []
                gravar(LIB, lib)
                return c
    raise FileNotFoundError(cid)


def amostra_voz(voz, velocidade):
    import asyncio, edge_tts
    pasta = RAIZ / "videos" / "_amostras"; pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / f"{slug(voz)}_{slug(velocidade)}.mp3"
    if not alvo.exists():
        texto = "O GTA 6 sai hoje à meia-noite, e tem coisa que ninguém te contou."
        asyncio.run(edge_tts.Communicate(texto, voz, rate=velocidade).save(str(alvo)))
    return f"/amostra/{alvo.name}"


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _arquivo(self, path, tipo=None):
        path = Path(path)
        if not path.is_file():
            return self._json({"erro": "não encontrado"}, 404)
        tam = path.stat().st_size
        tipo = tipo or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        ini, fim = 0, tam - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            ini = int(a) if a else 0
            fim = min(int(b) if b else tam - 1, tam - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tam}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(ini)
            resta = fim - ini + 1
            while resta > 0:
                bloco = f.read(min(1 << 20, resta))
                if not bloco:
                    break
                try:
                    self.wfile.write(bloco)
                except (BrokenPipeError, ConnectionResetError):
                    return
                resta -= len(bloco)

    def _post_atualizacao(self, corpo):
        acao = corpo.get("acao")
        if acao == "config":
            repo = (corpo.get("repo") or "").strip().replace("https://github.com/", "").strip("/")
            if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                raise ValueError("escreva o repositório como dono/nome (ex.: felipe/estudio-gta6)")
            return self._json({"ok": True, "config": ATU.salvar_config(repo=repo, automatico=bool(corpo.get("automatico", True)))})
        if acao == "verificar":
            return self._json({"ok": True, **ATU.verificar()})
        if acao == "aplicar":
            if ocupado() or CT.live_estado()["rodando"]:
                return self._json({"erro": "espere o trabalho atual (ou a gravação ao vivo) terminar"}, 409)
            r = ATU.aplicar()
            if r.get("aplicado"):
                ATU.registrar({"ok": True, **r})
            return self._json({"ok": True, **r})
        raise ValueError("ação inválida")

    def _dentro(self, base, rel):
        alvo = (base / rel).resolve()
        if base.resolve() not in alvo.parents:
            raise PermissionError("caminho inválido")
        return alvo

    def do_GET(self):
        u = urlparse(self.path)
        partes = [unquote(x) for x in u.path.strip("/").split("/") if x]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if not partes:
                return self._arquivo(AQUI / "estudio.html", "text/html; charset=utf-8")
            if partes[0] == "fonte" and len(partes) == 2:      # fontes da interface (woff2 locais, sem internet)
                f = self._dentro(FERR / "assets" / "fonts", partes[1])
                return self._arquivo(f, "font/woff2" if f.suffix == ".woff2" else "font/ttf")
            if partes == ["fonte"]:
                return self._arquivo(FERR / "assets" / "fonts" / "Bangers-Regular.ttf", "font/ttf")
            if partes[0] == "asset" and len(partes) == 2:
                return self._arquivo(self._dentro(FERR / "assets", partes[1]))
            if partes == ["api", "janela", "mostrar"]:      # 2ª abertura do programa: traz a janela de volta
                if callable(AO_MOSTRAR):
                    AO_MOSTRAR()
                return self._json({"ok": bool(callable(AO_MOSTRAR))})
            if partes == ["api", "estado"]:
                atual = _versao_txt()
                return self._json({"trabalho": TRABALHO, "versao": VERSAO, "lote": LOTE, "live": CT.live_estado(),
                                   "atualizado": ATU.ultimo(),
                                   "atualizacao": {"disponivel": bool(atual and VERSAO_INICIO and atual != VERSAO_INICIO),
                                                   "versao": atual, "reinicia": callable(AO_REINICIAR)}})
            if partes == ["api", "config"]:
                return self._json(config_estado())
            if partes == ["api", "resultados"]:
                return self._json(resultados())
            if partes[:2] == ["api", "revisao"] and len(partes) == 3:
                return self._json(revisao_lista(partes[2]))
            if partes[:2] == ["api", "revisao"] and len(partes) == 4:
                return self._arquivo(quadro_revisao(partes[2], int(partes[3].split(".")[0])), "image/jpeg")
            if partes == ["api", "projetos"]:
                return self._json({"projetos": lista_projetos(), "trabalho": TRABALHO})
            if partes[:2] == ["api", "projeto"] and len(partes) == 3:
                return self._json(info_projeto(projeto_dir(partes[2], exigir_roteiro=False)))
            if partes == ["api", "log"]:
                if q.get("projeto"):
                    log = projeto_dir(q["projeto"], False) / "log.txt"
                elif q.get("live"):
                    log = Path(CT.LIVE["log"] or "")
                elif q.get("corte"):
                    log = CT.trabalho_dir(q["corte"]) / "log.txt"
                elif q.get("biblioteca"):
                    log = BIB / "log.txt"
                else:
                    log = Path(TRABALHO["log"] or "")
                txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
                return self._json({"log": txt[-25000:], "trabalho": TRABALHO})
            if partes[:2] == ["api", "quadro"] and len(partes) == 4:
                return self._arquivo(quadro_do_corte(partes[2], int(partes[3].split(".")[0])), "image/jpeg")
            if partes[:2] == ["api", "clipe"] and len(partes) == 4:
                return self._arquivo(clipe_do_corte(partes[2], int(partes[3].split(".")[0])), "video/mp4")
            if partes[0] == "arquivo" and len(partes) == 3:
                p = projeto_dir(partes[1], False)
                return self._arquivo(self._dentro(p / "out", partes[2]))
            if partes[0] == "bib" and len(partes) >= 2:
                return self._arquivo(self._dentro(BIB, "/".join(partes[1:])))
            if partes[0] == "musica" and len(partes) == 2:
                return self._arquivo(self._dentro(MUSICAS, partes[1]))
            if partes[0] == "amostra" and len(partes) == 2:
                return self._arquivo(self._dentro(VIDEOS / "_amostras", partes[1]))
            if partes == ["api", "biblioteca"]:
                return self._json(biblioteca_resumo())
            if partes == ["api", "cenas"]:
                return self._json({"cenas": biblioteca_cenas(q.get("video"), q.get("filtro", "todas"), q.get("q", ""),
                                                            int(q.get("limite", 300)))})
            if partes == ["api", "midia"]:
                musicas = sorted(x.name for x in MUSICAS.iterdir()
                                 if x.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")) if MUSICAS.exists() else []
                assets = sorted(x.name for x in (FERR / "assets").glob("*.png"))
                return self._json({"musicas": musicas, "vozes": VOZES, "imagens": assets})
            if partes[:2] == ["api", "prompt"] and len(partes) == 3:
                if q.get("corrigir"):
                    return self._json({"prompt": prompt_correcao(partes[2])})
                return self._json({"prompt": prompt_chatgpt(partes[2])})
            if partes == ["api", "zernio"]:
                return self._json(zernio_estado())
            if partes == ["api", "lote"]:
                zc = _zernio().config()
                return self._json({"fila": fila_lote(), "lote": LOTE, "zernio": bool(zc["api_key"] and zc["contas"]),
                                   "sugestao_inicio": zernio_estado()["sugestao_inicio"], "intervalo_h": zc["intervalo_h"]})
            if partes == ["api", "temas"]:
                t = temas_md()
                return self._json({"temas": t, "historico": lista_projetos(), "restantes": len(t),
                                   "series_livres": temas_series(0)["livres"], "tendencias": tendencias(),
                                   "perguntas": ler(VIDEOS / "_perguntas.json") or {}, "segredos": CT.segredos(),
                                   "codigos": CT.codigos()})
            # ---- cortes e lives
            if partes == ["api", "atualizacao"]:
                c = ATU.config(); c.pop("token", None)
                return self._json({"config": c, "local": ATU.versao_local(), "ultimo": ATU.ultimo()})
            if partes == ["api", "cortes"]:
                return self._json({"trabalhos": CT.lista(), "ranking": CT.ranking(), "lives": CT.lives(), "live": CT.live_estado(), "trabalho": TRABALHO})
            if partes[:2] == ["api", "corte"] and len(partes) == 3:
                return self._json(CT.detalhe(partes[2]))
            if partes[:2] == ["api", "corte-quadro"] and len(partes) == 4:
                return self._arquivo(CT.quadro(partes[2], float(partes[3].rsplit(".", 1)[0])), "image/jpeg")
            if partes[0] == "corte" and len(partes) == 3 and partes[2] == "fonte":
                return self._arquivo(CT.fonte(partes[1]), "video/mp4")
            if partes[0] == "corte" and len(partes) >= 3:
                return self._arquivo(CT.arquivo(partes[1], "/".join(partes[2:])))
            return self._json({"erro": "rota desconhecida"}, 404)
        except FileNotFoundError:
            return self._json({"erro": "não encontrado"}, 404)
        except PermissionError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            return self._json({"erro": str(e)}, 500)

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"):
            return self._json({"erro": "origem não permitida"}, 403)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"erro": "json inválido"}, 400)
        u = urlparse(self.path).path
        try:
            if u == "/api/consertar":
                from checar_roteiro import consertar
                rot, mud = consertar(corpo["roteiro"])
                return self._json({"roteiro": rot, "mudancas": mud, "checagem": checar_roteiro(rot)})
            if u == "/api/config":
                return self._json(config_salvar(corpo))
            if u == "/api/skill":
                return self._json(gerar_skill())
            if u == "/api/abrir":
                alvo = Path(corpo.get("caminho", "")).resolve()
                if RAIZ.resolve() not in alvo.parents and alvo != RAIZ.resolve():
                    return self._json({"erro": "caminho fora da pasta de dados"}, 400)
                return self._json({"ok": abrir_no_explorer(alvo)})
            if u == "/api/variacao":
                import variacao
                return self._json(variacao.salvar(corpo))
            if u == "/api/aprovar":
                return self._json({"ok": True, "aprovado": aprovar(corpo["projeto"], bool(corpo.get("valor", True)))})
            if u == "/api/resultados":
                iniciar("zernio", lambda: [["zernio.py", "resultados"]], VIDEOS / "_zernio_log.txt", None, None)
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/atualizacao":
                try:
                    return self._post_atualizacao(corpo)
                except ATU.ErroAtualizacao as e:
                    return self._json({"erro": str(e)}, 409)
            if u == "/api/reiniciar":
                if ocupado():
                    return self._json({"erro": "espere o trabalho atual terminar"}, 409)
                if not callable(AO_REINICIAR):
                    return self._json({"erro": "feche o programa (ícone perto do relógio > Sair) e abra de novo"}, 409)
                threading.Timer(0.5, AO_REINICIAR).start()
                return self._json({"ok": True})
            if u == "/api/zernio/config":
                return self._json(zernio_config(corpo))
            if u == "/api/zernio/contas":
                return self._json({"contas": _zernio().contas((corpo.get("api_key") or "").strip() or None)})
            if u == "/api/temas/series":
                return self._json(temas_series(int(corpo.get("n") or 10)))
            if u == "/api/tendencias":
                per = corpo.get("periodo") if corpo.get("periodo") in ("relevancia", "hoje", "semana", "mes") else "relevancia"
                iniciar("tendencias", lambda: [["tendencias.py", "--periodo", per]], VIDEOS / "_tendencias_log.txt", None, None)
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/zernio/cancelar":
                if ocupado() and TRABALHO["acao"] == "zernio":
                    return self._json({"erro": "espere o envio ao Zernio terminar"}, 400)
                reg = _zernio().cancelar(projeto_dir(corpo["projeto"], False).name)
                return self._json({"ok": True, "horario": reg.get("horario")})
            if u == "/api/zernio/conferir":
                iniciar("zernio", lambda: [["zernio.py", "conferir"]], VIDEOS / "_zernio_log.txt", None, None)
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/zernio/agendar":
                zernio_agendar(corpo)
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/postado":
                p = projeto_dir(corpo["projeto"], False)
                if corpo.get("valor"):
                    (p / "postado.txt").write_text(datetime.datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
                elif (p / "postado.txt").exists():
                    (p / "postado.txt").unlink()
                return self._json({"ok": True, "postado": (p / "postado.txt").exists()})
            if u == "/api/lote":
                if corpo.get("acao") == "parar":
                    LOTE["parar"] = True
                    return self._json({"ok": True, "lote": LOTE})
                iniciar_lote(bool(corpo.get("agendar")))
                return self._json({"ok": True, "lote": LOTE, "trabalho": TRABALHO})
            if u == "/api/cortes/momentos":
                nome, etapas = CT.etapas_momentos(corpo)
                iniciar("momentos", lambda: etapas, CT.CORTES / nome / "log.txt", corte=nome)
                return self._json({"ok": True, "nome": nome, "trabalho": TRABALHO})
            if u == "/api/cortes/cortar":
                etapas = CT.etapas_cortar(corpo)
                nome, pick = corpo["nome"], int(corpo["pick"])
                projeto = corpo.get("projeto_atualizar")
                if projeto:
                    p = projeto_dir(projeto)
                    rot = ler(p / "roteiro.json") or {}
                    corte = rot.get("corte") or {}
                    if rot.get("tipo") != "clipe" or corte.get("trabalho") != nome or corte.get("pick") != pick or rot.get("idioma"):
                        raise ValueError("o projeto não corresponde a este clipe original")
                    if ler(p / "out" / "zernio.json"):
                        raise ValueError("cancele o agendamento antes de alterar este clipe")
                iniciar("cortar", lambda: etapas, CT.trabalho_dir(nome) / "log.txt", corte=nome,
                        depois=(lambda codigo, saida: atualizar_projeto_clipe(nome, pick, projeto, codigo)) if projeto
                        else (lambda codigo, saida: finalizar_corte(nome, pick, codigo)))
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/cortes/avaliar":
                return self._json({"ok": True, "avaliacao": CT.avaliar_clipe(corpo["nome"], int(corpo["pick"]))})
            if u == "/api/cortes/traduzir":
                etapas = CT.etapas_traduzir(corpo)
                iniciar("traduzir_clipe", lambda: etapas, CT.trabalho_dir(corpo["nome"]) / "log.txt", corte=corpo["nome"])
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/cortes/ganchos":
                return self._json(CT.ganchos(corpo["nome"], int(corpo["pick"])))
            if u == "/api/cortes/projeto":
                return self._json({"ok": True, "projeto": CT.para_projeto(corpo)})
            if u == "/api/cortes/apagar":
                return self._json({"ok": CT.apagar(corpo["nome"])})
            if u == "/api/cortes/lives":
                cons = re.sub(r"[^\w\s-]", "", corpo.get("consulta") or "gta 6")[:40] or "gta 6"
                CT.CORTES.mkdir(exist_ok=True)
                iniciar("lives", lambda: [["clipes/streams.py", "--query", cons]], CT.CORTES / "_lives_log.txt")
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/cortes/live":
                if corpo.get("acao") == "parar":
                    return self._json({"ok": CT.live_parar(), "live": CT.live_estado()})
                nome = CT.live_iniciar(corpo.get("url"), corpo.get("minutos"))
                return self._json({"ok": True, "nome": nome, "live": CT.live_estado()})
            if u == "/api/perguntas":
                iniciar("perguntas", lambda: [["clipes/perguntas.py", "--dias", str(float(corpo.get("dias") or 3))]],
                        VIDEOS / "_perguntas_log.txt")
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/segredo":
                return self._json({"ok": CT.marcar_segredo(corpo["id"], corpo["status"])})
            if u == "/api/traduzir-video":
                orig = projeto_dir(corpo["projeto"])
                lang = corpo.get("idioma") if corpo.get("idioma") in ("en", "es") else "en"
                novo = VIDEOS / f"{orig.name}_{lang}"
                rot, out, lib = str(novo / "roteiro.json"), str(novo / "out"), str(LIB)
                etapas = [["traduzir_roteiro.py", orig.name, "--idioma", lang], ["checar_roteiro.py", rot, "--lib", lib],
                          ["narrar.py", rot, "--saida", out], ["montar.py", rot, "--saida", out, "--lib", lib]]
                iniciar("traduzir_video", lambda: etapas, novo / "log.txt", novo / "status.txt", novo.name)
                return self._json({"ok": True, "projeto": novo.name, "trabalho": TRABALHO})
            if u == "/api/acao":
                if corpo.get("acao") not in ("checar", "previa", "gerar", "narrar", "capa", "ae"):
                    return self._json({"erro": "ação inválida"}, 400)
                acao_projeto(corpo["projeto"], corpo["acao"])
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/trabalho/cancelar":
                return self._json(cancelar_trabalho())
            if u == "/api/trabalho/repetir":
                return self._json(repetir_trabalho())
            if u == "/api/criar":
                nome = criar_video(corpo)
                return self._json({"ok": True, "projeto": nome})
            if u == "/api/roteiro":
                p = projeto_dir(corpo["projeto"])
                rot = corpo["roteiro"]
                if not isinstance(rot, dict) or not isinstance(rot.get("segmentos"), list):
                    return self._json({"erro": "roteiro inválido"}, 400)
                gravar(p / "roteiro.json", rot)
                return self._json({"ok": True, "checagem": checar_roteiro(rot)})
            if u == "/api/colar":
                return self._json({"ok": True, "checagem": colar_chatgpt(corpo["projeto"], corpo.get("texto", ""))})
            if u == "/api/checar":
                return self._json(checar_roteiro(corpo["roteiro"]))
            if u == "/api/enquadramento":
                return self._json({"ok": True, "enquadramento": salvar_enquadramento(
                    corpo["projeto"], int(corpo["idx"]), corpo.get("valor"))})
            if u == "/api/trocar-cena":
                return self._json({"ok": True, "clipes": trocar_cena(corpo["projeto"], int(corpo["idx"]), corpo["cena"])})
            if u == "/api/post":
                p = projeto_dir(corpo["projeto"])
                (p / "post.txt").write_text(corpo.get("texto", ""), encoding="utf-8")
                return self._json({"ok": True})
            if u == "/api/voz-amostra":
                return self._json({"url": amostra_voz(corpo.get("voz", VOZES[0][0]), corpo.get("velocidade", "+12%"))})
            if u == "/api/biblioteca":
                acao_biblioteca(corpo.get("acao"), corpo)
                return self._json({"ok": True, "trabalho": TRABALHO})
            if u == "/api/marcar":
                return self._json({"ok": True, "cena": marcar_cena(corpo["id"], corpo.get("descricao"),
                                                                    corpo.get("tags"), corpo.get("ruim"))})
            return self._json({"erro": "rota desconhecida"}, 404)
        except FileNotFoundError:
            return self._json({"erro": "projeto/cena não encontrado"}, 404)
        except (RuntimeError, ValueError) as e:
            return self._json({"erro": str(e)}, 409)
        except Exception as e:
            return self._json({"erro": f"{type(e).__name__}: {e}"}, 500)


AO_MOSTRAR = None          # o programa (app.py) põe aqui a função que mostra a janela
AO_REINICIAR = None        # e aqui a que reinicia o programa (para aplicar atualizações)


def servidor(porta=8765):
    """Cria o servidor (usado pelo programa app.py, que roda tudo num processo só)."""
    global PORTA
    PORTA = porta
    VIDEOS.mkdir(exist_ok=True); MUSICAS.mkdir(exist_ok=True)
    return ThreadingHTTPServer(("127.0.0.1", PORTA), H)


def main():
    global PORTA
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()
    PORTA = a.porta
    VIDEOS.mkdir(exist_ok=True); MUSICAS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), H)
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Estúdio GTA 6 rodando em {url}  (deixe esta janela aberta; Ctrl+C para fechar)")
    if not a.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
