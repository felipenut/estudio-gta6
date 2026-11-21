"""Transcrição na nuvem (Groq ou OpenAI), bem mais rápida que o Whisper no processador.

A chave fica só no seu computador, em ferramentas/config.json ("transcricao_chave"), e o Estúdio salva lá
pela tela Ajustes. Chave da Groq (começa com gsk_, tem plano grátis) ou da OpenAI (começa com sk-).
O áudio vai em pedaços de até 8 min (FLAC 16 kHz mono, ~8 MB cada), 4 de cada vez, e volta com o tempo de
cada palavra, no mesmo formato da transcrição local: [{"w", "s", "e"}].
"""
import json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import FERR, tool

CONFIG = FERR / "config.json"
PROVEDORES = {"groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3-turbo"),
              "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1")}
PEDACO = 8 * 60      # segundos por pedido (fica abaixo do limite de 25 MB do plano grátis)
SOBRA = 2            # segundos de contexto antes e depois de cada pedaço
SIMULTANEOS = 4
IDIOMAS = {"portuguese": "pt", "english": "en", "spanish": "es", "german": "de", "french": "fr", "russian": "ru",
           "italian": "it", "japanese": "ja", "korean": "ko", "chinese": "zh"}


def _config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def chave():
    return (os.environ.get("ESTUDIO_TRANSCRICAO_CHAVE") or _config().get("transcricao_chave") or "").strip()


def provedor(k=None):
    return "openai" if (k or chave()).startswith("sk-") else "groq"


def configurada():
    return bool(chave())


def salvar_chave(nova):
    """Grava (ou apaga, com texto vazio) a chave em config.json sem mexer no resto."""
    cfg = _config()
    nova = (nova or "").strip()
    if nova:
        cfg["transcricao_chave"] = nova
    else:
        cfg.pop("transcricao_chave", None)
    temporario = CONFIG.with_suffix(".novo")
    temporario.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(CONFIG)
    return configurada()


def _multipart(campos, dados, nome="audio.flac", tipo="audio/flac"):
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos:
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nome}"\r\n'
                  f"Content-Type: {tipo}\r\n\r\n".encode() + dados + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def _pedir(dados, k, tentativas=6):
    url, modelo = PROVEDORES[provedor(k)]
    url = os.environ.get("ESTUDIO_TRANSCRICAO_URL") or url
    corpo, tipo = _multipart([("model", modelo), ("response_format", "verbose_json"),
                              ("timestamp_granularities[]", "word"), ("temperature", "0")], dados)
    espera = 2.0
    for tentativa in range(tentativas):
        req = urllib.request.Request(url, data=corpo, method="POST",
                                     headers={"Authorization": f"Bearer {k}", "Content-Type": tipo})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (401, 403):
                raise RuntimeError(f"chave de transcrição recusada ({e.code}); confira em Ajustes") from None
            if e.code == 429 or e.code >= 500:
                try:
                    espera = max(espera, float(e.headers.get("retry-after") or 0))
                except ValueError:
                    pass
                if tentativa < tentativas - 1:
                    print(f"   a nuvem pediu para esperar {espera:.0f} s (limite de uso)…", flush=True)
                    time.sleep(min(espera, 90))
                    espera *= 2
                    continue
            raise RuntimeError(f"erro {e.code} na transcrição: {texto}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if tentativa < tentativas - 1:
                time.sleep(espera)
                espera *= 2
                continue
            raise RuntimeError(f"sem conexão com a nuvem ({e})") from None
    raise RuntimeError("a nuvem não respondeu")


def _audio(wav, inicio, duracao):
    """Recorta o pedaço em FLAC num arquivo (pelo pipe o FLAC sai sem a duração no cabeçalho)."""
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = os.path.join(pasta, "trecho.flac")
        r = subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{inicio:.2f}", "-t", f"{duracao:.2f}",
                            "-i", str(wav), "-ac", "1", "-ar", "16000", "-c:a", "flac", arquivo],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)
        if r.returncode:
            raise RuntimeError(f"não consegui preparar o áudio: {r.stderr.decode('utf-8', 'replace')[-200:]}")
        with open(arquivo, "rb") as f:
            return f.read()


def transcrever(wav, trechos, progresso=None):
    """trechos: [(início, fim)] em segundos. Devolve (palavras ordenadas, código do idioma ou None)."""
    k = chave()
    if not k:
        raise RuntimeError("chave de transcrição não configurada")
    pecas = []      # (pedido_ini, pedido_fim, guarda_ini, guarda_fim): guarda só as palavras que começam no pedaço
    for ini, fim in trechos:
        a = float(ini)
        while a < fim - 0.25:
            b = min(float(fim), a + PEDACO)
            pecas.append((max(float(ini), a - SOBRA), min(float(fim), b + SOBRA), a, b))
            a = b
    if not pecas:
        return [], None

    def uma(peca):
        p0, p1, g0, g1 = peca
        resposta = _pedir(_audio(wav, p0, p1 - p0), k)
        palavras = resposta.get("words")
        if palavras is None:        # alguns provedores só mandam por frase
            palavras = [w for s in resposta.get("segments", []) for w in (s.get("words") or [])]
        saida = []
        for w in palavras:
            s = p0 + float(w.get("start", 0))
            if g0 <= s < g1 and str(w.get("word", "")).strip():
                saida.append({"w": str(w["word"]).strip(), "s": round(s, 2), "e": round(p0 + float(w.get("end", 0)), 2)})
        return saida, (resposta.get("language") or "").lower()

    todas, idiomas, feitos = [], [], 0
    with ThreadPoolExecutor(max_workers=SIMULTANEOS) as pool:
        tarefas = [pool.submit(uma, p) for p in pecas]
        for t in as_completed(tarefas):
            palavras, idioma = t.result()
            todas += palavras
            idiomas.append(idioma)
            feitos += 1
            if progresso:
                progresso(feitos, len(pecas))
    idioma = max(set(idiomas), key=idiomas.count) if idiomas else ""
    return sorted(todas, key=lambda w: w["s"]), IDIOMAS.get(idioma, idioma if len(idioma) == 2 else None)


if __name__ == "__main__":      # python nuvem.py audio.wav  → testa a chave com os primeiros 30 s
    palavras, idioma = transcrever(sys.argv[1], [(0, 30)])
    print(f"ok ({provedor()}): {len(palavras)} palavras, idioma {idioma}: " + " ".join(w["w"] for w in palavras[:20]))
