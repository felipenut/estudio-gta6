"""Versão em outro idioma de um vídeo narrado: cria videos/<projeto>_<idioma>/ com o roteiro e o post traduzidos.

  python traduzir_roteiro.py <projeto> --idioma en|es

Traduz título, capa, falas, destaques, cartelas e o texto do post com a IA do Estúdio (chave NVIDIA).
As cenas escolhidas continuam as mesmas; a voz troca para uma voz neural do idioma e a música é a mesma do original.
O enquadramento manual não é copiado (os cortes mudam de tempo); o automático refaz sozinho.
"""
import argparse, json, re, sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from comum import ler_json, normalizar, salvar_json, tokens  # noqa: E402

RAIZ = AQUI.parent.parent
VIDEOS = RAIZ / "videos"
IDIOMAS = {"en": "inglês (EUA)", "es": "espanhol (América Latina)"}
VOZES = {"en": "en-US-GuyNeural", "es": "es-MX-JorgeNeural"}


def _cartela_txt(c):
    return c if isinstance(c, str) else (c or {}).get("texto", "") if isinstance(c, dict) else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto"); ap.add_argument("--idioma", choices=list(IDIOMAS), default="en")
    a = ap.parse_args()
    orig = (VIDEOS / a.projeto).resolve()
    if orig.parent != VIDEOS.resolve() or not (orig / "roteiro.json").exists():
        sys.exit(f"projeto não encontrado: {a.projeto}")
    rot = ler_json(orig / "roteiro.json")
    if (rot.get("idioma") or "pt") != "pt":
        sys.exit("este projeto já é uma tradução; traduza o original em português")
    post = (orig / "post.txt").read_text(encoding="utf-8") if (orig / "post.txt").exists() else ""
    segs = rot.get("segmentos") or []
    pedido = {"titulo": rot.get("titulo", ""), "capa": rot.get("capa", ""), "post": post,
              "segmentos": [{"texto": s.get("texto", ""), "destaque": s.get("destaque", []),
                             "cartela": _cartela_txt(s.get("cartela"))} for s in segs]}
    print(f"(1/2) traduzindo {len(segs)} falas para {IDIOMAS[a.idioma]} com a IA…", flush=True)
    import ia
    msgs = [{"role": "system", "content": "Você adapta roteiros de vídeos curtos (Shorts/Reels/TikTok) sobre GTA 6 para outro idioma. "
                                          "Escreva como um criador nativo: natural, rápido, com o mesmo humor (adapte trocadilhos que "
                                          "não funcionam). Não acrescente nem tire fatos, números, datas ou nomes. Escreva sempre "
                                          "'GTA 6' (nunca 'GTA VI') nas falas. Cada 'destaque' deve ser 1 ou 2 palavras que "
                                          "aparecem EXATAMENTE no texto traduzido daquele segmento. Cartelas curtas, em MAIÚSCULAS."},
            {"role": "user", "content": f"Traduza/adapte para {IDIOMAS[a.idioma]}. Devolva SOMENTE JSON com a MESMA estrutura e "
                                        f"exatamente {len(segs)} segmentos na mesma ordem. Campos vazios continuam vazios. "
                                        "No post, mantenha as hashtags (#GTA6 etc.) e troque as em português por equivalentes.\n\n"
                                        + json.dumps(pedido, ensure_ascii=False)}]
    r = ia.chat_json(msgs, temperatura=0.4, max_tokens=6000)
    novos = r.get("segmentos") or []
    if len(novos) != len(segs):
        sys.exit(f"a IA devolveu {len(novos)} segmentos em vez de {len(segs)}; tente de novo")
    print("(2/2) montando o projeto traduzido…", flush=True)
    novo = json.loads(json.dumps(rot))
    novo.pop("enquadramento", None)
    novo.update(idioma=a.idioma, original=orig.name, voz=VOZES[a.idioma], velocidade=rot.get("velocidade") or "+8%")
    if r.get("titulo"):
        novo["titulo"] = r["titulo"]
    if r.get("capa") or not rot.get("capa"):
        novo["capa"] = r.get("capa") or novo.get("titulo", "")
    novo.pop("capa_quadro", None)                       # os tempos mudam com a nova narração
    var = orig / "out" / "variacao.json"                # mesma música do original
    if not novo.get("musica") and var.exists():
        mus = (ler_json(var) or {}).get("musica")
        if mus:
            novo["musica"] = mus
    for s, t in zip(novo["segmentos"], novos):
        s["texto"] = (t.get("texto") or s.get("texto", "")).strip()
        tx = {normalizar(x) for x in tokens(s["texto"])}
        dest = [d for d in (t.get("destaque") or []) if d and all(normalizar(w) in tx for w in str(d).split())]
        s["destaque"] = [w for d in dest for w in str(d).split()][:2]
        if s.get("cartela") and t.get("cartela"):
            if isinstance(s["cartela"], dict):
                s["cartela"]["texto"] = t["cartela"]
            else:
                s["cartela"] = t["cartela"]
    dest_dir = VIDEOS / f"{orig.name}_{a.idioma}"
    dest_dir.mkdir(exist_ok=True)
    salvar_json(dest_dir / "roteiro.json", novo)
    (dest_dir / "post.txt").write_text((r.get("post") or "").strip() or novo.get("titulo", ""), encoding="utf-8")
    if (orig / "pedido.json").exists():
        ped = ler_json(orig / "pedido.json"); ped["traducao_de"] = orig.name
        salvar_json(dest_dir / "pedido.json", ped)
    (dest_dir / "status.txt").write_text("TRADUZIDO", encoding="utf-8")
    print(f"ok: {dest_dir.name} ({IDIOMAS[a.idioma]}, voz {VOZES[a.idioma]})", flush=True)


if __name__ == "__main__":
    main()
