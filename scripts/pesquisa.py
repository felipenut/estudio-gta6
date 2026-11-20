"""Pesquisa de notícias recentes para embasar o roteiro (sem chave de API).

Fontes: RSS do Bing Notícias (links diretos) e do Google Notícias (reserva). Depois baixa o texto dos artigos.
  python pesquisa.py "gta 6 lançamento"
"""
import html, json, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")


def _get(url, timeout=20, limite=2_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read(limite)
        cs = r.headers.get_content_charset() or "utf-8"
    try:
        return bruto.decode(cs, "replace")
    except LookupError:
        return bruto.decode("utf-8", "replace")


def _sem_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _link_real(link):
    """O Bing embrulha o link em apiclick.aspx?...&url=<real>."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    return q.get("url", [link])[0]


def _rss(url, fonte):
    itens = []
    raiz = ET.fromstring(_get(url).encode("utf-8"))
    for it in raiz.iter("item"):
        titulo = _sem_tags(it.findtext("title"))
        link = _link_real(it.findtext("link") or "")
        resumo = _sem_tags(it.findtext("description"))
        data = it.findtext("pubDate") or ""
        origem = ""
        for filho in it:
            if filho.tag.lower().endswith("source"):
                origem = _sem_tags(filho.text)
        if titulo and link:
            itens.append({"titulo": titulo, "url": link, "resumo": resumo[:400], "data": data,
                          "veiculo": origem, "via": fonte})
    return itens


def noticias(consulta, n=8):
    q = urllib.parse.quote(consulta)
    tentativas = [
        (f"https://www.bing.com/news/search?q={q}&format=rss&setlang=pt-br&cc=BR", "bing"),
        (f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419", "google"),
    ]
    vistos, res = set(), []
    for url, fonte in tentativas:
        try:
            for it in _rss(url, fonte):
                chave = it["titulo"].lower()[:60]
                if chave not in vistos:
                    vistos.add(chave)
                    res.append(it)
        except Exception as e:
            print(f"aviso: busca {fonte} falhou: {e}", file=sys.stderr)
        if len(res) >= n:
            break
    return res[:n]


def texto_da_pagina(url, max_chars=2500):
    """Texto dos parágrafos do artigo (bem simples, sem dependências)."""
    try:
        h = _get(url, timeout=15)
    except Exception:
        return ""
    h = re.sub(r"(?is)<(script|style|noscript|header|footer|nav|aside|form)[^>]*>.*?</\1>", " ", h)
    paras = [_sem_tags(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)]
    paras = [re.sub(r"\s+", " ", p) for p in paras if len(p) > 60]
    return " ".join(paras)[:max_chars]


def pesquisar(tema, n=6, com_texto=True):
    consulta = tema if re.search(r"gta", tema, re.I) else f"GTA 6 {tema}"
    itens = noticias(consulta, n + 4)
    saida = []
    for it in itens:
        if com_texto and "news.google.com" not in it["url"]:
            it["texto"] = texto_da_pagina(it["url"])
        else:
            it["texto"] = ""
        if it["texto"] or it["resumo"]:
            saida.append(it)
        if len(saida) >= n:
            break
    return saida


if __name__ == "__main__":
    r = pesquisar(" ".join(sys.argv[1:]) or "GTA 6")
    print(json.dumps([{k: (v[:200] if k == "texto" else v) for k, v in x.items()} for x in r], ensure_ascii=False, indent=1))
