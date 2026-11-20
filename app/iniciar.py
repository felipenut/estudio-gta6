"""Primeiro passo do EstudioGTA6.exe (roda no Python embutido do programa).

1. Lê a pasta de dados (pasta_dados.txt, escrita pelo instalador).
2. Se a pasta ainda não tem as ferramentas (ou elas são mais velhas que as do instalador), copia ferramentas_padrao.
   Arquivos seus (config.json, zernio.json, cache) nunca são apagados.
3. Cria biblioteca/, videos/, musicas/ e põe as músicas tema se musicas/ estiver vazia.
4. Abre o programa (ferramentas/scripts/app.py).
"""
import os, runpy, shutil, sys, traceback
from pathlib import Path

APP = Path(__file__).resolve().parent                    # pasta do programa instalado
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EstudioGTA6"


def pasta_dados():
    for f in (APP / "pasta_dados.txt", LOCAL / "pasta_dados.txt"):
        if f.exists():
            t = f.read_text(encoding="utf-8-sig").strip().strip('"')
            if t:
                return Path(os.path.expandvars(t))
    return Path.home() / "Documents" / "Estudio GTA 6"


def versao(p):
    try:
        return tuple(int(x) for x in p.read_text(encoding="utf-8-sig").strip().split("."))
    except Exception:
        return (0,)


def sincronizar(dados):
    padrao = APP / "ferramentas_padrao"
    destino = dados / "ferramentas"
    if not padrao.exists():
        return
    vp, vd = versao(padrao / "VERSAO.txt"), versao(destino / "VERSAO.txt")
    if (destino / "scripts" / "app.py").exists() and vd >= vp:
        return
    print(f"atualizando ferramentas {vd} -> {vp} em {destino}")
    for orig in padrao.rglob("*"):
        if orig.is_dir() or "__pycache__" in orig.parts:
            continue
        alvo = destino / orig.relative_to(padrao)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(orig, alvo)


def preparar(dados):
    for p in ("biblioteca", "videos", "musicas"):
        (dados / p).mkdir(parents=True, exist_ok=True)
    musicas = dados / "musicas"
    if not any(musicas.iterdir()) and (APP / "musicas_padrao").exists():
        for m in (APP / "musicas_padrao").iterdir():
            shutil.copy2(m, musicas / m.name)


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    dados = pasta_dados()
    dados.mkdir(parents=True, exist_ok=True)
    sincronizar(dados)
    preparar(dados)
    app = dados / "ferramentas" / "scripts" / "app.py"
    os.environ["PATH"] = str(APP / "bin") + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("PYTHONUTF8", "1"); os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ["GTA6_LOG_ARQUIVO"] = "1"
    sys.path.insert(0, str(app.parent))
    sys.argv = [str(app)]
    runpy.run_path(str(app), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        LOCAL.mkdir(parents=True, exist_ok=True)
        (LOCAL / "erro_ao_abrir.txt").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "O Estúdio não abriu. Detalhes em:\n" + str(LOCAL / "erro_ao_abrir.txt"),
                                             "Estúdio GTA 6", 0x10)
        except Exception:
            pass
        raise
