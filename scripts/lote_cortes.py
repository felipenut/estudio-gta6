"""Produz e retoma uma fila local de cortes de vários vídeos.

Uso: python lote_cortes.py caminho_da_fila.json
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import json
import os
import subprocess
import sys
import time

import cortes as CT

AQUI = Path(__file__).resolve().parent


def gravar_fila(arquivo, dados):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".novo")
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    for tentativa in range(4):
        try:
            temporario.replace(arquivo)
            return
        except PermissionError:
            if tentativa == 3:
                raise
            time.sleep(0.05)



def resumir_fila(fila):
    itens = fila.get("itens", [])
    return {"total": len(itens), "prontos": sum(i["estado"] == "pronto" for i in itens),
            "erros": sum(i["estado"] == "erro" for i in itens),
            "pendentes": sum(i["estado"] in ("pendente", "renderizando") for i in itens),
            "paralelos": fila.get("paralelos", 1), "pausada": bool(fila.get("pausada"))}


def fontes_disponiveis():
    """Lista somente fontes com momentos e vídeo disponíveis, sem abrir os MP4."""
    fontes = []
    for trabalho in CT.lista():
        if not trabalho["momentos"]:
            continue
        pasta = CT.trabalho_dir(trabalho["nome"])
        dados = CT._ler(pasta / "candidates.json") or {}
        if not dados.get("source") or not Path(dados["source"]).is_file():
            continue
        momentos = [c["n"] for c in dados.get("candidates", [])
                    if not corte_pronto(pasta, c["n"])]
        if momentos:
            fontes.append({"nome": trabalho["nome"], "titulo": trabalho["titulo"], "quantidade": len(momentos)})
    return fontes


def corte_pronto(pasta, pick):
    mp4 = pasta / "edits" / f"clip_{pick}.mp4"
    return mp4.is_file() and mp4.stat().st_size > 0 and bool(CT._ler(mp4.with_suffix(".json")))


def produzir_item(item, fila):
    nome, pick = item["nome"], item["pick"]
    try:
        pasta = CT.trabalho_dir(nome)
        candidatos = (CT._ler(pasta / "candidates.json") or {}).get("candidates", [])
        candidato = next((c for c in candidatos if c["n"] == pick), None)
        if candidato is None or [candidato["start"], candidato["end"]] != item["trecho"]:
            return False, "o momento mudou desde que entrou na fila; crie uma nova fila com esse trecho"
        if corte_pronto(pasta, pick):
            return True, "reaproveitado"
        gancho = candidato.get("gancho_sugerido") or ""
        opcoes = {"nome": nome, "pick": pick, "layout": fila["layout"], "legenda": fila["legenda"],
                  "gancho": gancho, "titulo": gancho}
        if fila["rapido"]:
            opcoes["edicao"] = ["pausas", "voz"]
        etapa = CT.etapas_cortar(opcoes)[0]
        ambiente = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        if fila["paralelos"] > 1:
            etapa += ["--threads", str(max(1, min(4, (os.cpu_count() or 2) // fila["paralelos"])))]
            ambiente["OPENCV_FOR_THREADS_NUM"] = "1"
        pasta_log = pasta / "edits"
        pasta_log.mkdir(exist_ok=True)
        arquivo_log = pasta_log / f"_lote_clip_{pick}.log"
        with arquivo_log.open("w", encoding="utf-8") as log:
            proc = subprocess.run([sys.executable, str(AQUI / etapa[0]), *etapa[1:]], cwd=CT.RAIZ,
                                  env=ambiente, stdout=log, stderr=subprocess.STDOUT, **CT.SEM_JANELA)
        if proc.returncode or not corte_pronto(pasta, pick):
            with arquivo_log.open("rb") as log:
                log.seek(max(0, arquivo_log.stat().st_size - 2048))
                linhas = log.read().decode("utf-8", errors="replace").splitlines()
            detalhe = next((l.strip() for l in reversed(linhas) if l.strip()), "")
            return False, f"falha ao renderizar: {detalhe or 'nenhum vídeo foi gravado'}"
        return True, "renderizado"
    except (OSError, ValueError, KeyError) as e:
        return False, str(e)


def produzir(arquivo):
    fila = CT._ler(arquivo)
    itens = fila["itens"]
    parar = arquivo.with_suffix(".parar")
    pendentes = iter(i for i in itens if i["estado"] in ("pendente", "renderizando"))
    ativos = {}
    inicio = ultimo_checkpoint = time.perf_counter()
    concluidos_desde_checkpoint = 0
    fila["pausada"] = False

    def iniciar_item(pool):
        if parar.exists():
            return False
        item = next(pendentes, None)
        if item is None:
            return False
        item.update(estado="renderizando", detalhe="")
        ativos[pool.submit(produzir_item, item, fila)] = item
        return True

    with ThreadPoolExecutor(max_workers=fila["paralelos"]) as pool:
        for _ in range(fila["paralelos"]):
            if not iniciar_item(pool):
                break
        while ativos:
            feitos, _ = wait(ativos, return_when=FIRST_COMPLETED)
            for tarefa in feitos:
                item = ativos.pop(tarefa)
                try:
                    ok, detalhe = tarefa.result()
                except Exception as e:
                    ok, detalhe = False, str(e)
                item.update(estado="pronto" if ok else "erro", detalhe=detalhe)
                concluidos_desde_checkpoint += 1
                agora = time.perf_counter()
                if concluidos_desde_checkpoint >= 4 or agora - ultimo_checkpoint >= 2:
                    gravar_fila(arquivo, fila)
                    ultimo_checkpoint = agora
                    concluidos_desde_checkpoint = 0
                estado = resumir_fila(fila)
                concluidos = estado["prontos"] + estado["erros"]
                print(f"({concluidos}/{estado['total']}) {item['nome']} · momento {item['pick']}: {detalhe}", flush=True)
                iniciar_item(pool)
    fila["pausada"] = parar.exists()
    gravar_fila(arquivo, fila)
    estado = resumir_fila(fila)
    print(f"{estado['prontos']} prontos · {estado['erros']} com erro · {estado['pendentes']} pendentes "
          f"({time.perf_counter() - inicio:.1f} s nesta execução)", flush=True)
    return int(bool(estado["erros"]))


if __name__ == "__main__":
    sys.exit(produzir(Path(sys.argv[1])))
