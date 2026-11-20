"""Etiqueta automaticamente as cenas sem tags da biblioteca usando o modelo de visão configurado.

  python etiquetar_ia.py [--lib biblioteca/biblioteca.json] [--video GTA6_Trailer_1] [--refazer] [--lote 4]

Manda as miniaturas em lotes (4 por pedido) e grava descrição + tags + "ruim" no biblioteca.json a cada lote.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ler_json, salvar_json
import ia

VOCAB = ("personagens: jason, lucia, npc, policia, gangue | lugares: vice city, leonida, praia, keys, pantano, estrada, "
         "cidade, balada, academia, loja, mapa, aeroporto, porto | ação: carro, perseguicao, assalto, tiro, explosao, "
         "fuga, danca, festa, animal, barco, aviao, moto, helicoptero | luz: dia, noite, por do sol, chuva | "
         "tipo: logo, texto, close, paisagem, vista aerea, gameplay, hud, humor, rede social")

PROMPT = """Você está catalogando cenas de vídeos de GTA 6 (Grand Theft Auto VI) para um editor de vídeos curtos.
Personagens principais: Jason (homem, cabelo comprido/boné, barba) e Lucia (mulher latina, cabelo cacheado preso).
Para CADA uma das {n} imagens, na ordem, devolva:
- "descricao": frase curta e concreta EM PORTUGUÊS (quem, o quê, onde, luz). Ex.: "Lucia de bandana assaltando loja de conveniência".
- "tags": 5 a 8 tags EM PORTUGUÊS, minúsculas, sem acento, preferindo este vocabulário: {vocab}
- "ruim": true se a imagem não serve como fundo de vídeo (tela preta, só texto/aviso/classificação indicativa, borrão, transição); senão false.
Se a imagem for só um logo ou texto (sem cena), use tags ["logo"] ou ["texto"] e ruim=false.
Responda SOMENTE com JSON: [{{"n": 1, "descricao": "...", "tags": ["..."], "ruim": false}}, ...]"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="biblioteca/biblioteca.json")
    ap.add_argument("--video")
    ap.add_argument("--refazer", action="store_true", help="refaz também as cenas que já têm tags")
    ap.add_argument("--lote", type=int, default=4)
    a = ap.parse_args()
    lib_path = Path(a.lib).resolve()
    base = lib_path.parent
    lib = ler_json(lib_path)
    fila = [c for v in lib["videos"] if not a.video or v["id"] == a.video for c in v["cenas"]
            if a.refazer or not c["tags"]]
    print(f"{len(fila)} cenas para etiquetar com {ia.config()['modelo_visao']}", flush=True)
    feitas = 0
    for i in range(0, len(fila), a.lote):
        lote = fila[i:i + a.lote]
        imgs = [base / c["thumb"] for c in lote]
        try:
            resp = ia.extrair_json(ia.visao(PROMPT.format(n=len(lote), vocab=VOCAB), imgs))
        except Exception as e:
            print(f"  lote {i // a.lote + 1}: erro ({e}); pulando", flush=True)
            time.sleep(2)
            continue
        if isinstance(resp, dict):
            resp = resp.get("cenas") or resp.get("imagens") or list(resp.values())[0]
        for k, c in enumerate(lote):
            r = next((x for x in resp if isinstance(x, dict) and x.get("n") == k + 1), resp[k] if k < len(resp) else None)
            if not isinstance(r, dict):
                continue
            if r.get("ruim"):
                c["tags"], c["descricao"] = ["ruim"], r.get("descricao", "descartada pela IA")
            else:
                c["descricao"] = str(r.get("descricao", ""))[:120]
                c["tags"] = [str(t).lower().strip() for t in r.get("tags", []) if str(t).strip()][:8] or ["gameplay"]
            feitas += 1
        salvar_json(lib_path, lib)
        print(f"  {min(i + a.lote, len(fila))}/{len(fila)}  ex.: {lote[0]['id']} -> {lote[0]['descricao'][:60]}", flush=True)
    print(f"ok: {feitas} cenas etiquetadas. Confira na aba Biblioteca do Estúdio.", flush=True)


if __name__ == "__main__":
    main()
