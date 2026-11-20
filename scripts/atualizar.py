"""Atualização automática pelo GitHub.

Ao abrir o programa (app.py), antes da janela aparecer:
  1. lê ferramentas/atualizacao.json  ->  {"repo": "dono/estudio-gta6", "ramo": "main", "automatico": true}
  2. compara o VERSAO.txt do GitHub com o daqui (números separados por ponto: 2026.11.20.1);
  3. se o do GitHub for MAIOR: baixa o zip do ramo, confere (tem scripts/app.py e estudio.py, VERSAO.txt bate,
     todo .py compila), guarda uma cópia dos arquivos que vão mudar em ferramentas/_backup/<versão antiga>/,
     copia os novos por cima e grava o VERSAO.txt por ÚLTIMO;
  4. o app.py reabre o programa já na versão nova.

Nunca apaga arquivo do usuário e nunca sobrescreve as chaves e preferências (PROTEGIDOS).
Sem internet, repo errado ou qualquer falha: o programa abre normalmente na versão atual (fica registrado no log).
Repositório privado: coloque um token de leitura em ferramentas/github_token.txt (esse arquivo não vai para o GitHub).

  python atualizar.py verificar      # só diz se há versão nova
  python atualizar.py aplicar        # baixa e aplica agora (com o programa fechado ou parado)
"""
import base64, io, json, os, shutil, sys, tempfile, time, urllib.request, zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
CONFIG = FERR / "atualizacao.json"
REGISTRO = FERR / "_atualizacao.json"
BACKUPS = FERR / "_backup"
TOKEN = FERR / "github_token.txt"
PROTEGIDOS = {"config.json", "zernio.json", "variacao.json", "primeira_config.json", "atualizacao.json",
              "github_token.txt", "app_log.txt", "_atualizacao.json"}
PASTAS_IGNORADAS = {"__pycache__", "_backup", ".git", ".github"}
MAX_ZIP = 150 * 1024 * 1024
UA = {"User-Agent": "EstudioGTA6-atualizador"}


class ErroAtualizacao(Exception):
    pass


# ------------------------------------------------------------------ configuração e versões
def config():
    c = {"repo": "", "ramo": "main", "automatico": True}
    try:
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    c["repo"] = (c.get("repo") or "").strip().strip("/")
    c["configurado"] = bool(c["repo"]) and "/" in c["repo"] and "USUARIO" not in c["repo"].upper()
    return c


def salvar_config(**kw):
    c = config()
    c.update(kw)
    c.pop("configurado", None)
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return config()


def versao_local():
    try:
        return (FERR / "VERSAO.txt").read_text(encoding="utf-8-sig").strip()
    except Exception:
        return "0"


def tupla(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("\ufeff").strip().split("."))
    except Exception:
        return (0,)


def _cabecalhos():
    h = dict(UA)
    try:
        t = TOKEN.read_text(encoding="utf-8").strip()
        if t:
            h["Authorization"] = f"Bearer {t}"
    except Exception:
        pass
    return h


def _get(url, timeout, limite=None):
    req = urllib.request.Request(url, headers=_cabecalhos())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read(limite + 1 if limite else -1)
    if limite and len(dados) > limite:
        raise ErroAtualizacao("download grande demais")
    return dados


def versao_remota(c=None, timeout=6):
    """VERSAO.txt do GitHub. Usa a API (sem atraso de cache); se falhar, o raw."""
    c = c or config()
    if not c["configurado"]:
        raise ErroAtualizacao("repositório do GitHub não configurado (ferramentas/atualizacao.json)")
    repo, ramo = c["repo"], c["ramo"] or "main"
    try:
        j = json.loads(_get(f"https://api.github.com/repos/{repo}/contents/VERSAO.txt?ref={ramo}", timeout))
        return base64.b64decode(j["content"]).decode("utf-8-sig").strip()
    except Exception as e1:
        try:
            return _get(f"https://raw.githubusercontent.com/{repo}/{ramo}/VERSAO.txt?t={int(time.time())}", timeout).decode("utf-8-sig").strip()
        except Exception as e2:
            raise ErroAtualizacao(f"não consegui ler a versão no GitHub ({e2 or e1})")


def verificar(timeout=6):
    c = config()
    loc = versao_local()
    rem = versao_remota(c, timeout)
    return {"local": loc, "remota": rem, "nova": tupla(rem) > tupla(loc), "repo": c["repo"], "ramo": c["ramo"]}


# ------------------------------------------------------------------ baixar, conferir e aplicar
def baixar_zip(c, timeout=90):
    repo, ramo = c["repo"], c["ramo"] or "main"
    urls = [f"https://api.github.com/repos/{repo}/zipball/{ramo}", f"https://codeload.github.com/{repo}/zip/refs/heads/{ramo}"]
    ultimo = None
    for u in urls:
        try:
            return _get(u, timeout, MAX_ZIP)
        except Exception as e:
            ultimo = e
    raise ErroAtualizacao(f"não consegui baixar a atualização ({ultimo})")


def _raiz_do_zip(pasta):
    """O zip do GitHub tem uma pasta 'dono-repo-hash/'. Aceita também o código dentro de 'ferramentas/'."""
    cands = [pasta] + [d for d in pasta.iterdir() if d.is_dir()]
    for base in list(cands):
        cands += [base / "ferramentas"]
    for c in cands:
        if (c / "scripts" / "app.py").is_file() and (c / "VERSAO.txt").is_file():
            return c
    raise ErroAtualizacao("o zip do GitHub não tem scripts/app.py e VERSAO.txt na raiz (ou em ferramentas/)")


def conferir(raiz, esperada=None):
    for f in ("scripts/app.py", "scripts/estudio.py", "scripts/estudio.html", "VERSAO.txt"):
        if not (raiz / f).is_file():
            raise ErroAtualizacao(f"atualização incompleta: falta {f}")
    v = (raiz / "VERSAO.txt").read_text(encoding="utf-8-sig").strip()
    if esperada and tupla(v) != tupla(esperada):
        raise ErroAtualizacao(f"o zip tem a versão {v}, mas o GitHub anunciou {esperada} (tente de novo em alguns minutos)")
    for py in (raiz / "scripts").rglob("*.py"):                 # nada de código quebrado chegando ao usuário
        try:
            compile(py.read_bytes(), str(py), "exec")
        except SyntaxError as e:
            raise ErroAtualizacao(f"erro de sintaxe em {py.relative_to(raiz)} (linha {e.lineno}): {e.msg}")
    return v


def _arquivos(raiz):
    for f in raiz.rglob("*"):
        if f.is_file() and not (set(f.relative_to(raiz).parts) & PASTAS_IGNORADAS) and f.name not in PROTEGIDOS:
            yield f


def aplicar_de_pasta(raiz, versao_nova):
    antiga = versao_local()
    bk = BACKUPS / antiga
    novos = [f for f in _arquivos(raiz) if f.name != "VERSAO.txt"]
    mudou = 0
    for f in novos:
        rel = f.relative_to(raiz)
        alvo = FERR / rel
        if alvo.exists():
            if alvo.read_bytes() == f.read_bytes():
                continue
            (bk / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alvo, bk / rel)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(alvo.name + ".novo")
        shutil.copy2(f, tmp)
        os.replace(tmp, alvo)
        mudou += 1
    if (FERR / "VERSAO.txt").exists():
        bk.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FERR / "VERSAO.txt", bk / "VERSAO.txt")
    shutil.copy2(raiz / "VERSAO.txt", FERR / "VERSAO.txt")      # por último: só agora a versão "vira"
    _limpar_backups()
    return {"de": antiga, "para": versao_nova, "arquivos": mudou}


def _limpar_backups(manter=3):
    if not BACKUPS.exists():
        return
    pastas = sorted((d for d in BACKUPS.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in pastas[manter:]:
        shutil.rmtree(d, ignore_errors=True)


def aplicar(info=None):
    c = config()
    info = info or verificar()
    if not info["nova"]:
        return {"aplicado": False, "motivo": "já está na versão mais nova", **info}
    dados = baixar_zip(c)
    with tempfile.TemporaryDirectory(prefix="estudio_atualiza_") as tmp:
        tmp = Path(tmp)
        try:
            zipfile.ZipFile(io.BytesIO(dados)).extractall(tmp)
        except zipfile.BadZipFile:
            raise ErroAtualizacao("o arquivo baixado não é um zip válido")
        raiz = _raiz_do_zip(tmp)
        v = conferir(raiz, info["remota"])
        r = aplicar_de_pasta(raiz, v)
    return {"aplicado": True, **r}


def registrar(dados):
    dados = {"quando": time.strftime("%Y-%m-%dT%H:%M:%S"), **dados}
    try:
        REGISTRO.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return dados


def ultimo():
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except Exception:
        return None


def ao_abrir():
    """Chamado pelo app.py. Nunca levanta exceção: no pior caso, abre a versão atual."""
    c = config()
    if not c["configurado"] or not c.get("automatico", True) or os.environ.get("GTA6_SEM_ATUALIZAR"):
        return {"aplicado": False, "motivo": "desligado ou sem repositório"}
    try:
        info = verificar(timeout=5)
        if not info["nova"]:
            return {"aplicado": False, **info}
        print(f"atualização encontrada: {info['local']} -> {info['remota']} ({c['repo']})", flush=True)
        r = aplicar(info)
        registrar({"ok": True, **r})
        print(f"atualizado: {r.get('arquivos')} arquivo(s), agora na versão {r.get('para')}", flush=True)
        return r
    except Exception as e:
        print(f"atualização automática não aplicada: {e}", flush=True)
        registrar({"ok": False, "erro": str(e)[:300], "local": versao_local()})
        return {"aplicado": False, "erro": str(e)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    try:
        if cmd == "verificar":
            i = verificar()
            print(f"local {i['local']}  ·  GitHub {i['remota']}  ->  " + ("HÁ VERSÃO NOVA" if i["nova"] else "em dia"))
        elif cmd == "aplicar":
            r = aplicar()
            registrar({"ok": True, **r}) if r.get("aplicado") else None
            print("aplicado: " + json.dumps(r, ensure_ascii=False))
        else:
            sys.exit(__doc__)
    except ErroAtualizacao as e:
        sys.exit(f"erro: {e}")


if __name__ == "__main__":
    main()
