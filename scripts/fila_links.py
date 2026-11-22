"""Fila de links em linha de produção: baixa, acha os momentos e corta vários vídeos ao mesmo tempo.

Enquanto um vídeo é analisado, os próximos já estão baixando e os cortes do anterior já estão renderizando.
O estado fica em cortes/_fila_links.json; se parar no meio, "retomar" continua de onde estava
(downloads e transcrições salvam o progresso, e cortes prontos são reaproveitados).

Uso: python fila_links.py caminho_da_fila.json
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import os
import subprocess
import sys
import threading
import time

import cortes as CT
import lote_cortes as LC

AQUI = Path(__file__).resolve().parent
ETAPA_ESTAVEL = {"baixando": "pendente", "analisando": "baixado", "cortando": "analisado"}
PESO = {"pendente": 0, "baixando": 0.05, "baixado": 0.25, "analisando": 0.3, "analisado": 0.55, "cortando": 0.6,
        "pronto": 1, "erro": 1}
TRAVA = threading.Lock()


def resumir(fila):
    itens = fila.get("itens", [])
    contar = lambda *estados: sum(i["estado"] in estados for i in itens)
    return {"medicao": fila.get("medicao"), "total": len(itens), "prontos": contar("pronto"), "erros": contar("erro"),
            "pendentes": len(itens) - contar("pronto", "erro"),
            "cortes_prontos": sum(i.get("cortes_prontos", 0) for i in itens), "pausada": bool(fila.get("pausada"))}


def _rodar(etapa, log_nome, pasta):
    """Roda uma etapa do Estúdio (script + argumentos) e guarda a saída num log próprio."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / log_nome
    ambiente = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    with arquivo.open("w", encoding="utf-8") as log:
        proc = subprocess.run([sys.executable, str(AQUI / etapa[0]), *etapa[1:]], cwd=CT.RAIZ, env=ambiente,
                              stdout=log, stderr=subprocess.STDOUT, **CT.SEM_JANELA)
    if not proc.returncode:
        return True, ""
    linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
    return False, next((l.strip() for l in reversed(linhas) if l.strip() and not l.startswith(" ")), "falhou")[:300]


def corpo_analise(item, op):
    return {"url": item["url"], "top": op["top"], "min": op["min"], "max": op["max"], "minutos": op["minutos"],
            "priorizar": op.get("priorizar") is True}


def baixar(item, op):
    nome, etapas = CT.etapas_momentos(corpo_analise(item, op))
    pasta = CT.CORTES / nome
    inicio = time.perf_counter()
    resultado = _rodar(["clipes/moments.py", item["url"], "--max-minutes", str(op["minutos"]), "--so-baixar"],
                  "_fila_download.log", pasta)
    item["tempo_fonte"] = round(time.perf_counter() - inicio, 3)
    return resultado


def analisar(item, op):
    nome, etapas = CT.etapas_momentos(corpo_analise(item, op))
    return _rodar(etapas[0], "_fila_analise.log", CT.CORTES / nome)


def escolher_cortes(item, op):
    pasta = CT.trabalho_dir(item["nome"])
    candidatos = (CT._ler(pasta / "candidates.json") or {}).get("candidates", [])
    melhores = sorted(candidatos, key=lambda c: -c.get("nota", 0))[:op["cortes_por_video"]]
    return [{"nome": item["nome"], "pick": c["n"], "trecho": [c["start"], c["end"]], "estado": "pendente", "detalhe": ""}
            for c in melhores]


def produzir(arquivo):
    fila = CT._ler(arquivo)
    op, itens = fila["opcoes"], fila["itens"]
    parar = arquivo.with_suffix(".parar")
    for item in itens:                       # retomada: volta quem parou no meio para a última etapa completa
        item["estado"] = ETAPA_ESTAVEL.get(item["estado"], item["estado"])
    fila["pausada"] = False
    import nuvem                              # cortes.py já põe scripts/clipes no caminho
    max_analises = 2 if nuvem.configurada() else 1        # com a nuvem, transcrever quase não usa o processador
    max_downloads, max_cortes = 2, op["paralelos"]
    estilo = {"layout": op["layout"], "legenda": op["legenda"], "paralelos": op["paralelos"], "rapido": op.get("rapido", False)}
    inicio = time.perf_counter()
    medicao = fila["medicao"] = {"segundos": 0, "novos": 0}
    ativos = {}                               # futuro -> (tipo, item, corte)

    def gravar():
        medicao["segundos"] = round(time.perf_counter() - inicio, 3)
        with TRAVA:
            LC.gravar_fila(arquivo, fila)
        estado = resumir(fila)
        feito = sum(PESO[i["estado"]] for i in itens)
        if itens:
            parcial = sum(min(1, i.get("cortes_prontos", 0) / max(1, len(i.get("cortes", [])))) * 0.4
                          for i in itens if i["estado"] == "cortando")
            print(f"progresso da fila: {int(100 * (feito + parcial) / len(itens))}% · {estado['prontos']}/{estado['total']} vídeos · "
                  f"{estado['cortes_prontos']} cortes prontos", flush=True)

    def em(tipo):
        return sum(1 for t, _, _ in ativos.values() if t == tipo)

    def iniciar_tarefas(pool):
        if parar.exists():
            return
        # cortes primeiro: é o que entrega resultado
        for item in itens:
            if item["estado"] != "cortando":
                continue
            for corte in item.get("cortes", []):
                if em("corte") >= max_cortes:
                    break
                if corte["estado"] == "pendente":
                    corte["estado"] = "renderizando"
                    item["estado"] = "cortando"
                    ativos[pool.submit(LC.produzir_item, corte, estilo)] = ("corte", item, corte)
        for item in itens:
            if em("analise") >= max_analises:
                break
            if item["estado"] == "baixado":
                item.update(estado="analisando", detalhe="achando os momentos")
                print(f"analisando: {item['url']}", flush=True)
                ativos[pool.submit(analisar, item, op)] = ("analise", item, None)
        # não baixa muito à frente da análise (cada vídeo ocupa ~1 GB)
        esperando = sum(i["estado"] in ("baixando", "baixado") for i in itens)
        for item in itens:
            if em("download") >= max_downloads or esperando >= 3:
                break
            if item["estado"] == "pendente":
                item.update(estado="baixando", detalhe="baixando")
                esperando += 1
                print(f"baixando: {item['url']}", flush=True)
                ativos[pool.submit(baixar, item, op)] = ("download", item, None)

    def concluir_item_se_pronto(item):
        cortes = item.get("cortes", [])
        if item["estado"] == "cortando" and all(c["estado"] in ("pronto", "erro") for c in cortes):
            ok = sum(c["estado"] == "pronto" for c in cortes)
            item.update(estado="pronto" if ok else "erro", cortes_prontos=ok,
                        detalhe=f"{ok} de {len(cortes)} cortes prontos" if cortes else "nenhum momento forte")
            print(f"pronto: {item.get('titulo') or item['url']} · {ok} corte(s)", flush=True)

    with ThreadPoolExecutor(max_workers=max_downloads + max_analises + max_cortes) as pool:
        for item in itens:                   # retomada de vídeos que já estavam nos cortes
            if item["estado"] != "analisado":
                continue
            try:
                if not item.get("cortes"):
                    item["cortes"] = escolher_cortes(item, op)
            except (OSError, ValueError, KeyError) as e:
                item.update(estado="erro", detalhe=f"análise: {e}")
                continue
            for corte in item["cortes"]:
                if corte["estado"] == "renderizando":
                    corte["estado"] = "pendente"
            item["estado"] = "cortando" if item["cortes"] else "pronto"
            concluir_item_se_pronto(item)
        iniciar_tarefas(pool)
        gravar()
        while ativos:
            feitos, _ = wait(ativos, return_when=FIRST_COMPLETED)
            for tarefa in feitos:
                tipo, item, corte = ativos.pop(tarefa)
                try:
                    ok, detalhe = tarefa.result()
                except Exception as e:      # noqa: BLE001 — qualquer falha vira erro do item, a fila segue
                    ok, detalhe = False, str(e)[:300]
                if tipo == "download":
                    item.update(estado="baixado" if ok else "erro", detalhe="baixado" if ok else f"download: {detalhe}")
                elif tipo == "analise":
                    if ok:
                        try:
                            pasta = CT.trabalho_dir(item["nome"])
                            info = CT._ler(pasta / "info.json") or {}
                            item["titulo"] = info.get("title") or item.get("titulo")
                            item["cortes"] = escolher_cortes(item, op)
                            item.update(estado="cortando" if item["cortes"] else "pronto", cortes_prontos=0,
                                        detalhe=f"{len(item['cortes'])} cortes na fila" if item["cortes"] else "nenhum momento forte")
                        except (OSError, ValueError, KeyError) as e:
                            item.update(estado="erro", detalhe=f"análise: {e}")
                    else:
                        item.update(estado="erro", detalhe=f"análise: {detalhe}")
                    print(f"{'analisado' if ok else 'falhou'}: {item.get('titulo') or item['url']} · {item['detalhe']}", flush=True)
                else:
                    medicao["novos"] += int(ok and detalhe == "renderizado")
                    corte.update(estado="pronto" if ok else "erro", detalhe=detalhe)
                    item["cortes_prontos"] = sum(c["estado"] == "pronto" for c in item["cortes"])
                    concluir_item_se_pronto(item)
                if parar.exists() and not fila.get("pausada"):
                    fila["pausada"] = True
                    print("pausando: termina o que já está rodando e para", flush=True)
            iniciar_tarefas(pool)
            gravar()
    fila["pausada"] = parar.exists() and resumir(fila)["pendentes"] > 0
    gravar()
    estado = resumir(fila)
    print(f"{estado['prontos']} vídeos prontos · {estado['cortes_prontos']} cortes · {estado['erros']} com erro · "
          f"{estado['pendentes']} pendentes ({time.perf_counter() - inicio:.0f} s nesta execução)", flush=True)
    return int(bool(estado["erros"]))


if __name__ == "__main__":
    sys.exit(produzir(Path(sys.argv[1])))
