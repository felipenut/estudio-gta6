"""Cortes prontos logo depois de achar os momentos: câmera do streamer, legenda palavra por palavra, gancho e
pergunta da IA, edição para retenção. Sai tudo em edits/clip_N.mp4 (e, com --projetos, já aparece em Agendar).

Uso: python auto_cortes.py <pasta do trabalho> [--n 5] [--layout auto|facecam|blur|fill] [--paralelos 0] [--projetos]

- A câmera é procurada UMA vez para o vídeo todo (nos melhores momentos) e usada em todos os cortes, em vez de
  rodar a detecção de novo em cada corte. Se o canal já tem enquadramento salvo (ajustado na tela), ele vale.
- Sem câmera no vídeo: formato Desfocado (jogo inteiro no meio, fundo desfocado).
- Renderiza 1 a 3 cortes ao mesmo tempo, conforme os núcleos do PC. Cortes já prontos são reaproveitados.
- Não agenda nada: os cortes ficam para você revisar e postar (ou ajustar na tela do corte).
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
import cortes as CT                                   # noqa: E402  (põe scripts/clipes no caminho)
from common import load_json, save_json               # noqa: E402

SEM_JANELA = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}


def paralelos_auto():
    nucleos = os.cpu_count() or 1
    return 1 if nucleos < 6 else 2 if nucleos < 12 else 3


def achar_camera(pasta, fonte, candidatos):
    """Procura a webcam nos 3 melhores momentos; guarda em cam_auto.json para não repetir."""
    cache = pasta / "cam_auto.json"
    if cache.exists():
        try:
            dados = load_json(cache)
            if dados.get("fonte") == str(fonte):
                return dados.get("modo"), dados.get("cam")
        except Exception:
            pass
    modo, cam = "none", None
    try:
        from facecam import find_cam
        from cut import caixa_do_rosto
        rosto = None
        for c in candidatos[:3]:
            centro = c.get("peak") or (c["start"] + c["end"]) / 2
            ini, fim = max(c["start"], centro - 15), min(c["end"], centro + 15)
            r = find_cam(str(fonte), ini, fim)
            print(f"   câmera no momento {c['n']}: {r.get('mode')} ({r.get('summary') or r.get('reason', '')})", flush=True)
            if r.get("mode") == "cam" and r.get("confidence", 0) >= 0.6:
                modo, cam = "cam", r["box"]
                break
            if r.get("mode") == "face" and rosto is None:
                rosto = caixa_do_rosto(list(r["box"]), "facecam")
        if cam is None and rosto is not None:
            modo, cam = "face", rosto
    except Exception as e:                            # sem OpenCV/modelo: segue sem câmera
        print(f"   não consegui procurar a câmera ({type(e).__name__}: {e})", flush=True)
    cam_txt = ":".join(f"{v:.4f}" for v in cam) if cam else None
    save_json(cache, {"fonte": str(fonte), "modo": modo, "cam": cam_txt})
    return modo, cam_txt


def rodar(etapa, log_arquivo, threads=None):
    etapa = list(etapa)
    if threads:
        etapa += ["--threads", str(threads)]
    ambiente = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    if threads:
        ambiente["OPENCV_FOR_THREADS_NUM"] = "1"
    with open(log_arquivo, "w", encoding="utf-8") as log:
        proc = subprocess.run([sys.executable, str(AQUI.parent / etapa[0]), *etapa[1:]], cwd=str(CT.RAIZ),
                              env=ambiente, stdout=log, stderr=subprocess.STDOUT, **SEM_JANELA)
    texto = Path(log_arquivo).read_text(encoding="utf-8", errors="replace")
    ultima = next((l.strip() for l in reversed(texto.splitlines()) if l.strip()), "")
    return proc.returncode, ultima


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--layout", choices=["auto", "facecam", "blur", "fill"], default="auto")
    ap.add_argument("--legenda", choices=["word", "bubble", "none"], default="word")
    ap.add_argument("--paralelos", type=int, default=0)
    ap.add_argument("--projetos", action="store_true", help="manda cada corte pronto para Agendar (sem agendar)")
    a = ap.parse_args()

    pasta = Path(a.pasta).resolve()
    dados = load_json(pasta / "candidates.json")
    candidatos = sorted(dados.get("candidates", []), key=lambda c: (-c.get("nota", 0), c["start"]))[:max(1, a.n)]
    if not candidatos:
        sys.exit("nenhum momento para cortar")
    fonte = Path(dados["source"])
    nome = pasta.name

    layout, cam = a.layout, None
    if layout in ("auto", "facecam"):
        if CT._ler(CT.arquivo_enquadramento(pasta)):
            layout = "facecam"
            print("   usando o enquadramento de câmera salvo para este canal", flush=True)
        else:
            modo, cam = achar_camera(pasta, fonte, candidatos)
            if cam:
                layout = "facecam"
                print(f"   câmera do streamer: {cam} ({'moldura' if modo == 'cam' else 'pelo rosto'}) — vale para todos os cortes", flush=True)
            else:
                layout = "blur" if a.layout == "auto" else "facecam"
                if layout == "blur":
                    print("   nenhuma câmera de streamer no vídeo: usando o formato Desfocado", flush=True)

    paralelos = a.paralelos or paralelos_auto()
    paralelos = max(1, min(paralelos, len(candidatos)))
    threads = max(1, min(4, (os.cpu_count() or 2) // paralelos)) if paralelos > 1 else None
    (pasta / "edits").mkdir(exist_ok=True)
    total = len(candidatos)
    print(f"cortando {total} momento(s), {paralelos} por vez ({layout})…", flush=True)

    def cortar(c):
        pick = c["n"]
        mp4 = pasta / "edits" / f"clip_{pick}.mp4"
        if mp4.is_file() and mp4.stat().st_size > 0 and (pasta / "edits" / f"clip_{pick}.json").is_file():
            return pick, True, "já estava pronto"
        gancho = (c.get("gancho_sugerido") or "").strip()
        corpo = {"nome": nome, "pick": pick, "layout": layout, "legenda": a.legenda, "gancho": gancho,
                 "titulo": gancho, "cam": cam, "salvar_padrao": False}
        log = pasta / "edits" / f"_auto_clip_{pick}.log"
        cod, ultima = rodar(CT.etapas_cortar(corpo)[0], log, threads)
        if cod and layout == "facecam":               # câmera sumiu nesse trecho: refaz desfocado
            corpo.update(layout="blur", cam=None)
            cod, ultima = rodar(CT.etapas_cortar(corpo)[0], log, threads)
            if not cod:
                return pick, True, "sem câmera neste trecho, saiu no formato Desfocado"
        return pick, not cod, ultima if cod else "pronto"

    prontos, erros, feitos = [], [], 0
    with ThreadPoolExecutor(max_workers=paralelos) as pool:
        for tarefa in as_completed([pool.submit(cortar, c) for c in candidatos]):
            pick, ok, detalhe = tarefa.result()
            feitos += 1
            (prontos if ok else erros).append(pick)
            print(f"corte {feitos}/{total} · momento {pick}: {detalhe}", flush=True)

    if a.projetos:
        for pick in sorted(prontos):
            try:
                projeto = CT.para_projeto({"nome": nome, "pick": pick})
                print(f"   momento {pick} pronto para postar em Agendar: {projeto}", flush=True)
            except Exception as e:
                print(f"   momento {pick}: não consegui mandar para Agendar ({e})", flush=True)

    resumo = {"prontos": sorted(prontos), "erros": sorted(erros), "layout": layout, "cam": cam}
    save_json(pasta / "edits" / "_auto_cortes.json", resumo)
    print(f"pronto: {len(prontos)} corte(s) em {pasta / 'edits'}" + (f" · {len(erros)} com erro" if erros else ""), flush=True)
    if erros and not prontos:
        sys.exit(1)


if __name__ == "__main__":
    main()
