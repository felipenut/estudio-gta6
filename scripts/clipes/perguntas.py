"""Perguntas dos fãs: o que o pessoal mais pergunta sobre GTA 6 no Reddit (e nos seus comentários), agrupado.

  python perguntas.py [--subs GTA6,GTA,GrandTheftAutoV] [--dias 3] [--comentarios comentarios.txt]

Salva videos/_perguntas.json. Cada grupo vira um tema "COMO FAZER" na tela Temas.
Reddit público (JSON), 1 pedido por segundo. (adaptado do questions-to-posts do gtavi-claudecode, licença MIT)
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import RAIZ
import questions as Q

SAIDA = RAIZ / "videos" / "_perguntas.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default="GTA6,GTA,GrandTheftAutoV,GTA6_Brasil")
    ap.add_argument("--dias", type=float, default=3)
    ap.add_argument("--comentarios", help="arquivo com comentários dos seus posts, um por linha")
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    subs = [s.strip() for s in a.subs.split(",") if s.strip()]
    print(f"(1/2) lendo r/{', r/'.join(subs)} (últimos {a.dias:g} dias)…", flush=True)
    itens = Q.collect_reddit(subs, a.dias)
    com = Path(a.comentarios) if a.comentarios else RAIZ / "videos" / "_comentarios.txt"
    if com.exists():
        itens += Q.collect_file(com)
    if not itens:
        sys.exit("nenhuma pergunta encontrada (Reddit vazio, bloqueado ou limitando). Tente mais tarde.")
    print(f"(2/2) agrupando {len(itens)} perguntas…", flush=True)
    grupos = Q.cluster(itens)[: a.top]
    saida = [{"pergunta": g["question"], "vezes": g["count"], "votos": g["votes"], "links": g["links"],
              "titulo_como": Q.howto_title(g["question"])} for g in grupos]
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"atualizado": time.strftime("%Y-%m-%dT%H:%M"), "subs": subs, "total": len(itens),
                                 "grupos": saida}, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in saida[:10]:
        print(f"  {g['vezes']:>3}x  {g['pergunta'][:90]}")
    print(f"pronto: {len(saida)} grupos de perguntas")


if __name__ == "__main__":
    main()
