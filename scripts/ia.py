"""Cliente de IA compatível com a API da OpenAI (padrão: NVIDIA, https://integrate.api.nvidia.com/v1).

A chave fica SÓ no seu computador, em ferramentas/config.json (o Estúdio salva lá). Nunca suba esse arquivo.

  python ia.py testar            # confere a chave e os modelos configurados
  python ia.py modelos           # lista os modelos disponíveis para a sua chave
"""
import base64, json, re, sys, time, urllib.error, urllib.request
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config.json"
PADRAO = {
    "base_url": "https://integrate.api.nvidia.com/v1",
    "api_key": "",
    "modelo_texto": "deepseek-ai/deepseek-v3.1",
    "modelo_visao": "meta/llama-4-maverick-17b-128e-instruct",
    "temperatura": 0.8,
}


class ErroIA(Exception):
    def __init__(self, msg, codigo=None):
        super().__init__(msg)
        self.codigo = codigo


def config():
    cfg = dict(PADRAO)
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def salvar_config(novos):
    cfg = config()
    for k, v in novos.items():
        if k in PADRAO and v is not None and v != "":
            cfg[k] = v
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg


def _req(caminho, corpo=None, timeout=240, tentativas=4):
    cfg = config()
    if not cfg["api_key"]:
        raise ErroIA("chave da API não configurada (Estúdio > Configurações)")
    url = cfg["base_url"].rstrip("/") + caminho
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    ultimo = None
    for t in range(tentativas):
        req = urllib.request.Request(url, data=dados, method="POST" if dados else "GET", headers={
            "Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json",
            "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:500]
            ultimo = f"HTTP {e.code}: {msg}"
            if e.code in (401, 403):
                raise ErroIA(f"chave recusada ({e.code}). Confira a chave em Configurações. {msg}")
            if e.code in (404, 410):
                raise ErroIA(f"modelo indisponível ({'descontinuado' if e.code == 410 else 'não encontrado'}): {msg}",
                             e.code)
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (2 ** t)))      # limite por minuto / instabilidade: espera e tenta de novo
                continue
            raise ErroIA(ultimo)
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo = str(e)
            time.sleep(3 * (t + 1))
    raise ErroIA(f"falha após {tentativas} tentativas: {ultimo}")


def limpar(txt):
    """Remove o raciocínio de modelos que pensam em voz alta (<think>...</think>)."""
    return re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S).strip()


def chat(mensagens, modelo=None, temperatura=None, max_tokens=4096, _retentar=True):
    cfg = config()
    corpo = {"model": modelo or cfg["modelo_texto"], "messages": mensagens, "max_tokens": max_tokens,
             "temperature": cfg["temperatura"] if temperatura is None else temperatura, "top_p": 0.95, "stream": False}
    try:
        r = _req("/chat/completions", corpo)
    except ErroIA as e:
        if modelo is None and _retentar and e.codigo in (404, 410):   # modelo do config saiu do ar: escolhe outro
            print(f"aviso: {cfg['modelo_texto']} indisponível; procurando outro modelo...", file=sys.stderr, flush=True)
            novo = testar(auto=True)
            if novo.get("texto") and not str(novo["texto"]).startswith("ERRO"):
                print(f"usando {novo['texto']}", file=sys.stderr, flush=True)
                return chat(mensagens, None, temperatura, max_tokens, _retentar=False)
        raise
    try:
        return limpar(r["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        raise ErroIA(f"resposta inesperada: {str(r)[:300]}")


def extrair_json(txt):
    """Extrai um objeto/lista JSON mesmo com cercas ou texto ao redor."""
    txt = limpar(txt)
    cerca = chr(96) * 3
    blocos = [m.group(1) for m in re.finditer(re.escape(cerca) + r"(?:json)?\s*(.*?)" + re.escape(cerca), txt, re.S | re.I)]
    blocos.append(txt)
    decodificador = json.JSONDecoder()

    def sem_virgula_final(bruto):
        saida, em_str, escape = [], False, False
        for i, ch in enumerate(bruto):
            if em_str:
                saida.append(ch)
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    em_str = False
                continue
            if ch == '"':
                em_str = True
                saida.append(ch)
            elif ch == ",":
                proximo = i + 1
                while proximo < len(bruto) and bruto[proximo].isspace():
                    proximo += 1
                if proximo >= len(bruto) or bruto[proximo] not in "}]":
                    saida.append(ch)
            else:
                saida.append(ch)
        return "".join(saida)

    for bloco in blocos:
        for i, ch in enumerate(bloco):
            if ch not in "{[":
                continue
            bruto = bloco[i:]
            for candidato in (bruto, sem_virgula_final(bruto)):
                try:
                    valor, _ = decodificador.raw_decode(candidato)
                    if isinstance(valor, (dict, list)):
                        return valor
                except json.JSONDecodeError:
                    continue
    if not re.search(r"[\[{]", txt):
        raise ErroIA("a IA não devolveu JSON")
    raise ErroIA("JSON incompleto ou inválido na resposta da IA")


def chat_json(mensagens, modelo=None, temperatura=None, max_tokens=6000, tentativas=2):
    ultimo, conversa = None, list(mensagens)
    total = max(1, int(tentativas))
    for tentativa in range(total):
        txt = chat(conversa, modelo, temperatura, max_tokens if tentativa == 0 else min(6000, int(max_tokens * 1.25)))
        try:
            return extrair_json(txt)
        except (ErroIA, json.JSONDecodeError) as e:
            ultimo = e
            if tentativa + 1 < total:
                conversa = conversa + [{"role": "assistant", "content": txt[-1200:]},
                                       {"role": "user", "content": "A resposta anterior veio incompleta ou fora do JSON. Refaça somente como JSON minificado e completo."}]
    raise ErroIA(f"não consegui ler o JSON da IA: {ultimo}")


def visao(prompt, imagens, modelo=None, max_tokens=2500, temperatura=0.2):
    """Pergunta sobre imagens (caminhos de JPG/PNG). Envia como data URL base64."""
    conteudo = [{"type": "text", "text": prompt}]
    for p in imagens:
        b = base64.b64encode(Path(p).read_bytes()).decode()
        tipo = "png" if str(p).lower().endswith(".png") else "jpeg"
        conteudo.append({"type": "image_url", "image_url": {"url": f"data:image/{tipo};base64,{b}"}})
    cfg = config()
    return chat([{"role": "user", "content": conteudo}], modelo or cfg["modelo_visao"], temperatura, max_tokens)


def listar_modelos():
    r = _req("/models", timeout=60)
    return sorted(m.get("id", "") for m in r.get("data", []))


# preferências (prefixos), da melhor para a pior; dentro do mesmo prefixo, versões mais novas primeiro
PREF_TEXTO = ["deepseek-ai/deepseek-v3", "qwen/qwen3", "moonshotai/kimi-k2", "deepseek-ai/deepseek",
              "meta/llama-4-maverick", "nvidia/llama-3.3-nemotron-super", "nvidia/nemotron", "mistralai/mistral-large",
              "openai/gpt-oss", "meta/llama-4", "qwen/qwen", "meta/llama"]
PREF_VISAO = ["meta/llama-4-maverick", "qwen/qwen3-vl", "qwen/qwen2.5-vl", "nvidia/nemotron-nano-12b-v2-vl",
              "meta/llama-4-scout", "meta/llama-3.2-90b-vision", "nvidia/llama-3.1-nemotron-nano-vl",
              "microsoft/phi-4-multimodal", "google/gemma-3"]
_EXCLUIR = ("embed", "rerank", "guard", "reward", "safety", "parse", "coder", "math", "retriever", "clip", "ocr",
            "detector", "tts", "asr", "translate")
# imagem 8x8 para testar modelos de visão (sem dependências)
_PNG_TESTE = ("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGP4r6CAFTEMLQkAYVlPwYHvrpQAAAAASUVORK5CYII=")


def _candidatos(disponiveis, prefs, visao=False):
    disp = [m for m in disponiveis if not any(x in m.lower() for x in _EXCLUIR)]
    if visao:
        disp = [m for m in disp if any(k in m.lower() for k in ("vision", "-vl", "vl-", "maverick", "scout",
                                                                 "multimodal", "gemma-3"))]
    out = []
    for pref in prefs:
        for m in sorted((m for m in disp if m.lower().startswith(pref) and m not in out), reverse=True):
            out.append(m)
    return out


def _testar_texto(modelo):
    return chat([{"role": "user", "content": "Responda só: ok"}], modelo=modelo, max_tokens=20, temperatura=0)


def _testar_visao(modelo):
    conteudo = [{"type": "text", "text": "Que cor predomina nesta imagem? Responda em uma palavra."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _PNG_TESTE}}]
    return chat([{"role": "user", "content": conteudo}], modelo=modelo, max_tokens=20, temperatura=0)


def testar(auto=True, max_tentativas=6):
    """Testa os modelos configurados. Se algum estiver fora do ar/descontinuado, procura e salva outro que funcione."""
    cfg = config()
    res = {"texto": None, "visao": None, "trocou": {}, "tentados": []}
    try:
        disponiveis = listar_modelos()
    except ErroIA as e:
        res["texto"] = f"ERRO: {e}"
        res["disponiveis"] = []
        return res
    res["disponiveis"] = disponiveis
    for tipo, chave, prefs, teste in (("texto", "modelo_texto", PREF_TEXTO, _testar_texto),
                                      ("visao", "modelo_visao", PREF_VISAO, _testar_visao)):
        fila = [cfg[chave]] + ([m for m in _candidatos(disponiveis, prefs, tipo == "visao") if m != cfg[chave]]
                               if auto else [])
        for m in fila[:max_tentativas + 1]:
            try:
                teste(m)
                res[tipo] = m
                if m != cfg[chave]:
                    res["trocou"][chave] = {"de": cfg[chave], "para": m}
                    salvar_config({chave: m})
                break
            except ErroIA as e:
                res["tentados"].append(f"{m}: {str(e)[:120]}")
                if e.codigo in (401, 403):
                    res[tipo] = f"ERRO: {e}"
                    return res
        if not res[tipo]:
            res[tipo] = f"ERRO: nenhum modelo de {tipo} respondeu ({len(res['tentados'])} tentados)"
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "modelos":
        print("\n".join(listar_modelos()))
    else:
        print(json.dumps(testar(), ensure_ascii=False, indent=1))
