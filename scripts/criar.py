"""Cria um projeto de vídeo completo a partir de um TEMA usando a IA configurada (NVIDIA ou outra compatível).

  python criar.py "o que muda na polícia do GTA 6" [--data-post 2026-11-20] [--pasta videos/NOME]
                  [--notas "foque no sistema de procurado"] [--fontes "https://...,https://..."] [--sem-pesquisa]

Passos: pesquisa notícias -> IA escreve roteiro + escolhe cenas + escreve o post -> checador -> a IA corrige os
erros (até 3 rodadas) -> completa cenas que faltarem -> salva videos/<data>_<tema>/roteiro.json e post.txt.
Última linha impressa: "PROJETO: <nome da pasta>".
"""
import argparse, datetime, json, math, re, sys, unicodedata
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ler_json, salvar_json, tokens, normalizar, RAIZ_SKILL
import ia, pesquisa
import biblioteca as B
from checar_roteiro import checar, PALAVRAS_POR_SEG

RAIZ = RAIZ_SKILL.parent
VIDEOS = RAIZ / "videos"
LIB = RAIZ / "biblioteca" / "biblioteca.json"
ASSETS_IMG = ["seta_cima.png", "seta_baixo.png", "seta_esquerda.png", "seta_direita.png", "seta_diagonal.png",
              "circulo.png", "x_vermelho.png", "check_verde.png"]
SEG_POR_CORTE = 2.4


def slug(txt, n=40):
    s = unicodedata.normalize("NFD", txt.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n].strip("-") or "video"


def lista_cenas(lib, uso=None):
    """Lista compacta para a IA: apelido curto -> id real. Esconde cenas 'ruim'.
    uso = {id: vezes nos últimos vídeos}: essas cenas ganham '(usada)' para a IA preferir outras."""
    uso = uso or {}
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    apelidos, linhas = {}, []
    for k, v in enumerate(lib["videos"]):
        pref = letras[k % 26] + ("" if k < 26 else str(k // 26))
        bloco, ult = [], None
        for c in v["cenas"]:
            if "ruim" in c["tags"] or not c["tags"]:
                continue
            ap = f"{pref}{c['id'].split('#')[-1]}"
            apelidos[ap] = c["id"]
            txt = f"{c['descricao']} [{', '.join(c['tags'][:7])}]" + (" (usada)" if uso.get(c["id"]) else "")
            if ult and ult[1] == txt:              # cenas seguidas iguais viram uma faixa: "G42 a G56"
                bloco[-1] = f"{ult[0]} a {ap}: {txt}"
            else:
                ult = (ap, txt)
                bloco.append(f"{ap}: {txt}")
        if bloco:
            linhas.append(f"## {v['id']}")
            linhas += bloco
    return apelidos, "\n".join(linhas)


def historico(excluir=None):
    ganchos, ctas = [], []
    for r in sorted(VIDEOS.glob("*/roteiro.json")):
        if excluir and r.parent == excluir:
            continue
        rot = ler_json(r)
        segs = rot.get("segmentos", [])
        if segs:
            ganchos.append(segs[0].get("texto", ""))
            ctas.append(segs[-1].get("texto", ""))
    return ganchos[-10:], ctas[-10:]


def exemplos():
    exs = []
    for p in [RAIZ_SKILL / "references" / "roteiro_exemplo.json", *sorted(VIDEOS.glob("*/roteiro.json"))[:2]]:
        try:
            r = ler_json(p)
            exs.append("\n".join(f"- [{s.get('tipo')}] {s.get('texto')}"
                                 + (f"  (cartela: {s['cartela'] if isinstance(s['cartela'], str) else s['cartela'].get('texto')})"
                                    if s.get("cartela") else "") for s in r["segmentos"]))
        except Exception:
            pass
    return exs[:2]


REGRAS = """FÓRMULA (siga à risca):
- 150 a 185 palavras no total (60–70 s de narração). Frases curtas (6–14 palavras), português falado do Brasil.
- 10 a 14 segmentos; cada segmento = 1 ideia visual, 1–2 frases.
- Segmento 1 tipo "gancho": até 16 palavras, contém "GTA", fato chocante/curioso logo de cara. PROIBIDO saudação ("oi", "fala galera", "hoje vou").
- Segmento 2 tipo "promessa": loop aberto ("fica até o final porque...").
- Corpo: blocos fato -> reação/piada -> micro-gancho ("mas isso não é nada...", "só que...", "repara...").
- Um "cta" leve no meio (salva/manda pro amigo). Penúltimo ou último: "payoff" com o fato mais forte.
- Último segmento tipo "cta": pergunta que gere comentário + "segue pra parte 2".
- Pelo menos 1 "piada" e no máximo 2 "duplo_sentido" (humor leve de TV aberta, a insinuação se desfaz na hora). NUNCA conteúdo sexual explícito, menores, assédio, preconceito.
- Escreva "GTA 6" e "GTA 5" no texto (nunca "GTA VI" no texto falado). Números em algarismos (212, 449, 19).
- tipos permitidos: gancho, promessa, historia, curiosidade, piada, duplo_sentido, comparacao, pergunta, cta, payoff.
- "destaque": 1–2 itens, CADA UM UMA ÚNICA PALAVRA (sem espaço) copiada do texto do segmento (vão em amarelo).
- "cartela": texto curto em MAIÚSCULAS para os 3–5 números/datas mais fortes (ex.: "212 GB", "19/11 - 00H"). Sem "•".
- "sfx": "impacto" nas 2–3 revelações mais fortes (inclusive o gancho).
- "imagem" (opcional): {"arquivo": um de %s, "escala": 0.2-0.35, "y": 250 (acima da imagem) ou 1520 (abaixo da legenda)}. Use seta_baixo no CTA final; x_vermelho/check_verde para mito/verdade.
FATOS: use SOMENTE fatos das FONTES abaixo ou de notícias confiáveis que você pesquisar agora. Sem fonte para um número/data, não cite o número. Rumor = diga "segundo rumores". Não invente nomes de missões, personagens ou recursos.
CENAS ("clipes"): para cada segmento, liste apelidos da LISTA DE CENAS (ex.: "A12") que ILUSTREM o que é dito — 1 cena para cada ~6 palavras do segmento (mínimo 2). Não repita cena no vídeo. Cenas de logo/texto só no gancho ou quando a fala for sobre data/capa. Para piada/reação prefira close de rosto; para números, cenas de impacto (explosão, perseguição, vista aérea)."""

FORMATO = """Responda SOMENTE com um JSON neste formato:
{"titulo": "...", "capa": "TEXTO CURTO DA CAPA (até 7 palavras)",
 "segmentos": [{"tipo": "gancho", "texto": "...", "destaque": ["..."], "cartela": "...", "sfx": "impacto",
                "clipes": ["A12", "C3"]}, ...],
 "post": "legenda curta do post com 1 pergunta + emojis moderados + 6 a 8 hashtags (#gta6 #gtavi ...)",
 "fontes_usadas": [1, 3]}
Campos "cartela", "sfx" e "imagem" só quando fizer sentido."""


def montar_prompt(tema, data_post, fontes, notas, apelidos_txt, ganchos, ctas):
    hoje = datetime.date.today().isoformat()
    f_txt = "\n\n".join(f"[{i + 1}] {f['titulo']} ({f.get('veiculo') or f['url']}, {f.get('data', '')})\n"
                        f"{(f.get('texto') or f.get('resumo') or '')[:1800]}" for i, f in enumerate(fontes)) or "(sem fontes)"
    exs = exemplos()
    sistema = ("Você é roteirista de vídeos curtos virais (TikTok/Reels/Shorts) sobre GTA 6 para o público brasileiro. "
               "Seus roteiros prendem do início ao fim: gancho forte, curiosidades com números concretos, histórias, "
               "piadas leves, micro-ganchos e CTA. Você escreve como um criador brasileiro falando, não como um robô.\n\n"
               + REGRAS % ASSETS_IMG)
    usuario = (f"DATA DE HOJE: {hoje}. O VÍDEO SERÁ POSTADO EM: {data_post} (ajuste 'hoje/amanhã/ontem' para essa data).\n"
               f"TEMA: {tema}\n" + (f"NOTAS DO CRIADOR: {notas}\n" if notas else "") +
               "\nEXEMPLOS DE ROTEIROS APROVADOS (estilo a seguir, não copie):\n"
               + "\n\n".join(f"Exemplo {i + 1}:\n{e}" for i, e in enumerate(exs)) +
               ("\n\nGANCHOS JÁ USADOS (não repita):\n- " + "\n- ".join(ganchos) if ganchos else "") +
               ("\nCTAs JÁ USADOS (varie):\n- " + "\n- ".join(ctas) if ctas else "") +
               f"\n\nFONTES:\n{f_txt}\n\nLISTA DE CENAS (apelido: descrição [tags]):\n{apelidos_txt}\n\n{FORMATO}")
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def converter(resp, apelidos, fontes):
    """JSON da IA -> roteiro.json da skill (apelidos -> ids reais). Devolve (roteiro, problemas)."""
    problemas = []
    segs = []
    usados = set()
    for i, s in enumerate(resp.get("segmentos", [])):
        seg = {"tipo": s.get("tipo", "curiosidade"), "texto": str(s.get("texto", "")).strip(),
               "destaque": [d for d in s.get("destaque", []) if isinstance(d, str)][:2]}
        for k in ("cartela", "sfx", "imagem"):
            if s.get(k):
                seg[k] = s[k]
        if isinstance(seg.get("cartela"), str):
            seg["cartela"] = seg["cartela"].replace("•", "-").upper()
        if seg.get("sfx") not in (None, "impacto", "whoosh", "pop"):
            seg.pop("sfx")
        img = seg.get("imagem")
        if img and (not isinstance(img, dict) or Path(str(img.get("arquivo", ""))).name not in ASSETS_IMG):
            seg.pop("imagem")
        clipes = []
        for ap in s.get("clipes", []):
            ap = str(ap).strip().upper()
            if ap in apelidos and apelidos[ap] not in usados:
                clipes.append({"cena": apelidos[ap]})
                usados.add(apelidos[ap])
            elif ap not in apelidos:
                problemas.append(f"seg {i + 1}: cena '{ap}' não existe na LISTA DE CENAS")
        seg["clipes"] = clipes
        segs.append(seg)
    usadas = [fontes[n - 1] for n in resp.get("fontes_usadas", []) if isinstance(n, int) and 0 < n <= len(fontes)]
    rot = {"titulo": resp.get("titulo") or "", "capa": (resp.get("capa") or resp.get("titulo") or "").upper(),
           "fontes": [f"{f['titulo']} — {f['url']}" for f in (usadas or fontes)],
           "voz": "pt-BR-AntonioNeural", "velocidade": "+12%", "estilo": {"ritmo_corte": SEG_POR_CORTE},
           "segmentos": segs}
    return rot, problemas, resp.get("post", "")


def completar_cenas(rot, lib_path, projeto=None):
    """Garante ~1 cena por corte de 2,4 s; completa pela busca na biblioteca quando a IA deu poucas.
    Cenas usadas nos últimos 10 vídeos perdem pontos (menos repetição entre vídeos)."""
    usados = {c["cena"] for s in rot["segmentos"] for c in s["clipes"]}
    uso = B.uso_recente(lib_path, 10, projeto)
    for s in rot["segmentos"]:
        n = max(2, math.ceil(len(tokens(s["texto"])) / PALAVRAS_POR_SEG / SEG_POR_CORTE))
        if len(s["clipes"]) >= n:
            continue
        consulta = " ".join(t for t in tokens(s["texto"]) if len(normalizar(t)) > 3)
        for _, _, _, c in B.buscar(lib_path, consulta, 30, usados, uso):
            if len(s["clipes"]) >= n:
                break
            if {"logo", "texto", "capa", "data"} & set(c["tags"]):
                continue
            s["clipes"].append({"cena": c["id"]})
            usados.add(c["id"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tema")
    ap.add_argument("--data-post", default=(datetime.date.today() + datetime.timedelta(days=1)).isoformat())
    ap.add_argument("--pasta")
    ap.add_argument("--notas", default="")
    ap.add_argument("--fontes", default="", help="links separados por vírgula para usar como fonte")
    ap.add_argument("--sem-pesquisa", action="store_true")
    a = ap.parse_args()

    lib = ler_json(LIB)
    apelidos, apelidos_txt = lista_cenas(lib)
    print(f"biblioteca: {len(apelidos)} cenas úteis", flush=True)

    fontes = []
    for url in [u.strip() for u in a.fontes.split(",") if u.strip()]:
        fontes.append({"titulo": url, "url": url, "texto": pesquisa.texto_da_pagina(url)})
    if not a.sem_pesquisa:
        print("pesquisando notícias...", flush=True)
        try:
            fontes += pesquisa.pesquisar(a.tema, n=6)
        except Exception as e:
            print(f"aviso: pesquisa falhou ({e}); seguindo sem fontes", flush=True)
    for i, f in enumerate(fontes, 1):
        print(f"  [{i}] {f['titulo'][:90]}", flush=True)

    pasta = Path(a.pasta).resolve() if a.pasta else VIDEOS / f"{a.data_post}_{slug(a.tema)}"
    pasta.mkdir(parents=True, exist_ok=True)
    ganchos, ctas = historico(excluir=pasta)
    msgs = montar_prompt(a.tema, a.data_post, fontes, a.notas, apelidos_txt, ganchos, ctas)

    print("escrevendo o roteiro com a IA...", flush=True)
    rot, post = None, ""
    for rodada in range(1, 4):
        resp = ia.chat_json(msgs, max_tokens=6000)
        rot, problemas, post = converter(resp, apelidos, fontes)
        erros, avisos = checar(rot, str(LIB))
        erros = problemas + erros
        n_pal = sum(len(tokens(s["texto"])) for s in rot["segmentos"])
        print(f"rodada {rodada}: {len(rot['segmentos'])} segmentos, {n_pal} palavras, "
              f"{len(erros)} erro(s), {len(avisos)} aviso(s)", flush=True)
        if not erros:
            break
        for e in erros:
            print("   ERRO", e, flush=True)
        msgs = msgs + [{"role": "assistant", "content": json.dumps(resp, ensure_ascii=False)},
                       {"role": "user", "content": "O checador encontrou estes ERROS:\n- " + "\n- ".join(erros)
                        + ("\nAvisos (melhore se der):\n- " + "\n- ".join(avisos) if avisos else "")
                        + "\nCorrija e devolva o JSON COMPLETO no mesmo formato."}]
    completar_cenas(rot, str(LIB))
    rot["data_post"] = a.data_post
    rot["tema"] = a.tema
    salvar_json(pasta / "roteiro.json", rot)
    (pasta / "post.txt").write_text(post.strip() + "\n", encoding="utf-8")
    erros, avisos = checar(rot, str(LIB))
    for e in erros:
        print("ERRO  ", e, flush=True)
    for w in avisos:
        print("AVISO ", w, flush=True)
    print(f"roteiro salvo: {pasta / 'roteiro.json'}", flush=True)
    print(f"PROJETO: {pasta.name}", flush=True)
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
