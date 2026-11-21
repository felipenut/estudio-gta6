"""Confere se o roteiro segue a fórmula antes de narrar/montar (rode SEMPRE antes do narrar.py).

  python checar_roteiro.py videos/<projeto>/roteiro.json [--lib biblioteca/biblioteca.json]

Mostra ERROS (precisa corrigir) e AVISOS (vale revisar). Sai com código 1 se houver erro.
"""
import argparse, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ler_json, normalizar, tokens, RAIZ_SKILL

PALAVRAS_POR_SEG = 2.7          # pt-BR-AntonioNeural a +12% fala ~2,7 palavras/s
TIPOS = {"gancho", "promessa", "historia", "curiosidade", "piada", "duplo_sentido", "comparacao",
         "pergunta", "cta", "payoff"}
VERBOS_CTA = r"\b(segue|siga|comenta|comente|salva|salve|manda|mande|compartilha|curte|ativa)\b"
MICRO_GANCHOS = r"(\bmas\b|s[oó] que|o pior|agora vem|espera|detalhe:|isso n[aã]o [eé] nada|e tem mais|" \
                r"no final|ningu[eé]m (viu|percebeu)|repara)"


def checar(rot, lib_path):
    erros, avisos = [], []
    segs = rot.get("segmentos", [])
    if not segs:
        return ["roteiro sem segmentos"], []
    texto = " ".join(s.get("texto", "") for s in segs)
    n = len(tokens(texto))
    dur = n / PALAVRAS_POR_SEG
    print(f"{n} palavras, {len(segs)} segmentos, ~{dur:.0f}s de narração estimada")
    if n < 130 or n > 200:
        erros.append(f"{n} palavras: fora da faixa (alvo 150–185 para 60–70 s)")
    elif n < 150 or n > 185:
        avisos.append(f"{n} palavras: um pouco fora do alvo 150–185")

    # gancho
    g = segs[0]
    ng = len(tokens(g.get("texto", "")))
    if g.get("tipo") != "gancho":
        erros.append("o 1º segmento deve ser tipo 'gancho'")
    if ng > 16:
        erros.append(f"gancho com {ng} palavras: corte para ≤ 16 (cabe em ~3 s)")
    if not re.search(r"\bgta\b", g.get("texto", ""), re.I):
        avisos.append("o gancho não fala 'GTA': o tema precisa aparecer no 1º segundo")
    if re.match(r"\s*(oi|ol[aá]|e a[ií]|fala (galera|pessoal)|hoje (eu )?vou|neste v[ií]deo)", g.get("texto", ""), re.I):
        erros.append("gancho começa com saudação/apresentação: comece direto no fato chocante")

    # CTA
    ctas = [i for i, s in enumerate(segs) if s.get("tipo") == "cta" or re.search(VERBOS_CTA, s.get("texto", ""), re.I)]
    if not ctas:
        erros.append("nenhum CTA (segue/comenta/salva/manda...)")
    elif ctas[-1] < len(segs) - 2:
        erros.append("falta CTA no final (último ou penúltimo segmento)")
    if len(ctas) < 2:
        avisos.append("só 1 CTA: considere um CTA leve no meio (~50% do vídeo)")
    if not re.search(r"\?", " ".join(segs[i]["texto"] for i in ctas[-1:] if ctas)):
        avisos.append("CTA final sem pergunta: pergunta gera comentário")

    # variedade e ritmo
    tipos = [s.get("tipo", "") for s in segs]
    for t in set(tipos) - TIPOS - {""}:
        avisos.append(f"tipo desconhecido '{t}' (use: {', '.join(sorted(TIPOS))})")
    if len(set(tipos)) < 4:
        avisos.append(f"pouca variedade de tipos ({', '.join(sorted(set(tipos)))}): misture curiosidade, história, piada...")
    if not ({"piada", "duplo_sentido"} & set(tipos)):
        avisos.append("nenhuma piada: o estilo pede humor leve")
    if tipos.count("duplo_sentido") > 2:
        erros.append("mais de 2 duplos sentidos: no máximo 1–2 por vídeo")
    mg = len(re.findall(MICRO_GANCHOS, texto, re.I))
    if mg < 2:
        avisos.append(f"só {mg} micro-gancho(s) ('mas...', 'só que...', 'repara...'): use 2+ para segurar a retenção")
    for k, frase in enumerate(re.split(r"(?<=[.!?])\s+", texto)):
        if len(frase.split()) > 24:
            avisos.append(f"frase longa ({len(frase.split())} palavras): '{frase[:50]}...'")

    # por segmento
    lib = ler_json(lib_path) if lib_path and Path(lib_path).exists() else None
    cenas = {c["id"]: c for v in lib["videos"] for c in v["cenas"]} if lib else {}
    usados = {}
    sem_destaque = 0
    for i, s in enumerate(segs):
        tx = s.get("texto", "")
        rot_i = f"seg {i + 1} ({s.get('tipo', '?')})"
        nw = len(tokens(tx))
        if nw > 32:
            avisos.append(f"{rot_i}: {nw} palavras, divida em dois segmentos (1 ideia visual por segmento)")
        if re.search(r"\bGTA\s+(VI|V)\b", tx):
            erros.append(f"{rot_i}: escreva 'GTA 6'/'GTA 5' no texto (a voz lê 'VI' errado); use VI só em cartela")
        dest = s.get("destaque", [])
        if not dest:
            sem_destaque += 1
        norm_tx = {normalizar(t) for t in tokens(tx)}
        for d in dest:
            if normalizar(d) not in norm_tx:
                erros.append(f"{rot_i}: destaque '{d}' não aparece no texto")
        if not s.get("clipes") and not (s.get("busca") or s.get("tags")):
            erros.append(f"{rot_i}: sem 'clipes' e sem 'busca'/'tags', não há como escolher imagem")
        for ref in s.get("clipes", []):
            if "cena" in ref:
                if lib is None:
                    avisos.append("biblioteca não encontrada: não deu para validar os ids de cena")
                    lib = {"videos": []}
                elif ref["cena"] not in cenas and cenas:
                    erros.append(f"{rot_i}: cena '{ref['cena']}' não existe na biblioteca")
                elif cenas and "ruim" in cenas[ref["cena"]]["tags"]:
                    erros.append(f"{rot_i}: cena '{ref['cena']}' está marcada como ruim")
                if ref["cena"] in usados and usados[ref["cena"]] != i:
                    avisos.append(f"{rot_i}: cena '{ref['cena']}' já usada no seg {usados[ref['cena']] + 1}")
                usados.setdefault(ref["cena"], i)
            elif "arquivo" in ref and not Path(ref["arquivo"]).exists():
                erros.append(f"{rot_i}: arquivo de clipe não encontrado: {ref['arquivo']}")
        imgs = s.get("imagem") or []
        for img in ([imgs] if isinstance(imgs, dict) else imgs):
            a = img.get("arquivo", "")
            if not Path(a).exists() and not (RAIZ_SKILL / "assets" / Path(a).name).exists():
                erros.append(f"{rot_i}: imagem não encontrada: {a}")
    if sem_destaque > len(segs) * 0.4:
        avisos.append(f"{sem_destaque} segmentos sem 'destaque': marque 1–2 palavras-chave em amarelo")
    if not any(s.get("cartela") for s in segs):
        avisos.append("nenhuma cartela: um número/data grande na tela (ex.: '19 DE NOVEMBRO') reforça o fato principal")
    if (rot.get("idioma") or "pt") != "pt":   # versão traduzida: regras de contagem/CTA em português viram só aviso
        leves = ("palavras: fora da faixa", "nenhum CTA", "falta CTA", "gancho com", "gancho começa")
        avisos += [f"(tradução) {e}" for e in erros if any(k in e for k in leves)]
        erros = [e for e in erros if not any(k in e for k in leves)]
    return erros, avisos


def consertar(rot):
    """Corrige sozinho os erros mecânicos (sem mudar o sentido do texto). Devolve (roteiro, lista de mudanças)."""
    mud = []
    segs = rot.get("segmentos", [])
    for i, s in enumerate(segs):
        r = f"seg {i + 1}"
        if i == 0 and s.get("tipo") != "gancho":
            s["tipo"] = "gancho"; mud.append(f"{r}: tipo virou 'gancho'")
        elif s.get("tipo") not in TIPOS:
            mud.append(f"{r}: tipo '{s.get('tipo')}' virou 'curiosidade'"); s["tipo"] = "curiosidade"
        tx = s.get("texto", "")
        novo = re.sub(r"\bGTA\s+VI\b", "GTA 6", re.sub(r"\bGTA\s+V\b", "GTA 5", tx))
        if novo != tx:
            s["texto"] = tx = novo; mud.append(f"{r}: 'GTA VI/V' virou 'GTA 6/5' na fala")
        norm = {normalizar(t): t for t in tokens(tx)}
        dest, orig = [], s.get("destaque") or []
        if isinstance(orig, str):
            orig = [orig]
        for d in orig:      # 1 palavra por item: a mais longa que está no texto ("Los Santos" -> "Santos")
            ws = sorted((w.strip(".,!?;:") for w in str(d).split() if normalizar(w) in norm), key=len, reverse=True)
            ws = [w for w in ws if normalizar(w) not in [normalizar(x) for x in dest]]
            if ws:
                dest.append(ws[0])
        dest = dest[:2]
        if dest != orig:
            mud.append(f"{r}: destaque {orig} -> {dest}")
            s["destaque"] = dest
        if isinstance(s.get("cartela"), str):
            c = s["cartela"].replace("•", "-").upper().strip()
            if c != s["cartela"]:
                s["cartela"] = c; mud.append(f"{r}: cartela em maiúsculas")
            if not c:
                s.pop("cartela")
        if s.get("sfx") and s["sfx"] not in ("impacto", "whoosh", "pop"):
            mud.append(f"{r}: efeito '{s['sfx']}' removido"); s.pop("sfx")
    return rot, mud


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roteiro")
    ap.add_argument("--lib", default="biblioteca/biblioteca.json")
    a = ap.parse_args()
    erros, avisos = checar(ler_json(a.roteiro), a.lib)
    for e in erros:
        print("ERRO  ", e)
    for w in avisos:
        print("AVISO ", w)
    print("OK, pode narrar." if not erros else f"{len(erros)} erro(s): corrija antes de narrar.")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
