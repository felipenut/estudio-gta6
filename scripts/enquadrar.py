"""Enquadramento automático: onde recortar a janela 9:16 dentro de uma cena 16:9.

Ordem de prioridade do "assunto" da cena:
  0. CONTEXTO: se a fala (ou as tags da cena) cita algo que o detector de objetos acha no quadro
     ("lancha" -> barco, "viatura" -> carro, "flamingo" -> ave...), o foco vai nesse objeto (e acompanha se ele anda);
  1. ROSTOS (detector YuNet, incluído em assets/modelos; cai para Haar se não houver);
     - cabem todos na janela  -> foco fixo centralizado neles;
     - não cabem (casal nas pontas) -> PANORÂMICA do rosto mais à esquerda até o mais à direita;
  2. sem rostos: OBJETOS detectados (YOLOX: pessoa, carro, moto, barco, avião, animais...) por importância × tamanho;
  3. nada detectado: o que se MEXE (diferença entre quadros) + o que chama o olho (saliência) + leve viés ao centro.
Sempre tela cheia: quem decide "inteiro" é o montar.py (só para logo/texto/capa/mapa).

decidir(arquivo, ini, dur, crop=None, src_w, src_h, fala="", cena="") -> {"foco": float | [ini, fim], "layout": "cheio", "motivo": str}
"""
import subprocess
from pathlib import Path
import numpy as np

MODELO_YUNET = Path(__file__).resolve().parent.parent / "assets" / "modelos" / "face_yunet_2023mar.onnx"
LARGURA = 640
_YN = {"det": None, "ok": None}
_CASC = None


def _quadros(arquivo, ini, dur, crop, largura=LARGURA):
    """3 quadros do trecho (25/50/75%), já sem as tarjas pretas."""
    import cv2
    out = []
    for frac in (0.25, 0.5, 0.75):
        t = ini + dur * frac
        vf = (f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}," if crop else "") + f"scale={largura}:-2"
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(arquivo), "-frames:v", "1",
                            "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        if r.returncode == 0 and r.stdout:
            img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                out.append(img)
    return out


def _yunet():
    if _YN["ok"] is None:
        try:
            import cv2
            _YN["det"] = cv2.FaceDetectorYN.create(str(MODELO_YUNET), "", (320, 320), 0.6, 0.3, 5000)
            _YN["ok"] = True
        except Exception:
            _YN["ok"] = False
    return _YN["det"] if _YN["ok"] else None


def _haar():
    global _CASC
    if _CASC is None:
        _CASC = []
        try:
            import cv2, os
            if hasattr(cv2, "CascadeClassifier") and getattr(cv2, "data", None):
                for n in ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
                    c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, n))
                    if not c.empty():
                        _CASC.append(c)
        except Exception:
            pass
    return _CASC


def rostos(img):
    """[(x, largura, área, confiança)] dos rostos encontrados."""
    import cv2
    h, w = img.shape[:2]
    det = _yunet()
    res = []
    if det is not None:
        det.setInputSize((w, h))
        _, f = det.detect(img)
        for r in (f if f is not None else []):
            x, y, fw, fh = r[:4]
            if fw > w * 0.02:
                res.append((float(x), float(fw), float(fw * fh), float(r[-1])))
        return res
    g = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    for k, c in enumerate(_haar()):
        for flip in ((False, True) if k == 1 else (False,)):
            gg = cv2.flip(g, 1) if flip else g
            for (x, y, fw, fh) in c.detectMultiScale(gg, 1.1, 5, minSize=(int(h * 0.08), int(h * 0.08))):
                res.append((float(w - x - fw if flip else x), float(fw), float(fw * fh), 0.7))
    return res


def _saliencia(img):
    """Resíduo espectral (Hou & Zhang 2007)."""
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = g.shape
    p = cv2.resize(g, (128, max(8, int(128 * h / w))))
    f = np.fft.fft2(p)
    amp, fase = np.log(np.abs(f) + 1e-6), np.angle(f)
    s = np.abs(np.fft.ifft2(np.exp(amp - cv2.blur(amp, (3, 3)) + 1j * fase))) ** 2
    s = cv2.resize(cv2.GaussianBlur(s.astype(np.float32), (0, 0), 3), (w, h))
    return s / (s.max() + 1e-9)


def _norm(v):
    s = v.sum()
    return v / s if s > 0 else v


def _foco_de_centro(cx, jan, w):
    return round(float(min(max((cx - jan / 2) / (w - jan), 0.0), 1.0)), 3)


_AVISO_OBJ = {"ok": False}


def _objetos(quadros):
    """Detecção de objetos nos quadros; se o OpenCV do PC não rodar o modelo, segue sem ela (só rostos/movimento)."""
    try:
        import objetos as O
        if O._net() is None:
            return None, []
        return O, [O.detectar(q, 0.22) for q in quadros]
    except Exception as e:
        if not _AVISO_OBJ["ok"]:
            print(f"aviso: detector de objetos falhou ({e}); seguindo só com rostos/movimento")
            _AVISO_OBJ["ok"] = True
        return None, []


def _foco_objetos(O, dets, alvo, jan, w, h, motivo_extra="", area_min=0.004, conf_min=None, rostos_cx=()):
    """Escolhe o objeto principal (do contexto, se houver) e decide foco fixo ou panorâmica acompanhando."""
    area_q = float(w * h)

    def cand(ds):
        out = []
        for d in ds:
            if alvo and d["coco"] not in alvo:
                continue
            x, y, bw, bh = d["box"]
            a = bw * bh / area_q
            if a < area_min or d["conf"] < (conf_min if conf_min is not None else (0.22 if alvo else 0.4)):
                continue
            peso = O.ASSUNTO.get(d["coco"], ("", 0.3))[1]
            out.append(dict(d, cx=x + bw / 2, a=a, nota=peso * d["conf"] * (a ** 0.5)))
        return out
    cs = [cand(ds) for ds in dets]
    if len(cs) >= 3:      # consistência: a classe precisa aparecer em 2+ quadros (evita troca de plano e bichinho de fundo)
        from collections import Counter
        pres = Counter(c for k in cs for c in {d["coco"] for d in k})
        meio_forte = {d["coco"] for d in cs[1] if d["conf"] >= 0.7 and d["a"] >= 0.04}   # nítido no quadro do meio
        cs = [[d for d in k if pres[d["coco"]] >= 2 or d["coco"] in meio_forte] for k in cs]
    ordem = sorted(range(len(cs)), key=lambda k: (abs(k - 1), -len(cs[k])))
    ordem = [k for k in ordem if cs[k]]
    if not ordem:
        return None
    k0 = ordem[0]
    best = max(cs[k0], key=lambda d: d["nota"])
    # junta objetos da mesma classe que cabem juntos na janela (ex.: casal, dois carros)
    grupo = [d for d in cs[k0] if d["coco"] == best["coco"] and d["nota"] >= best["nota"] * 0.45]
    esq = min(d["box"][0] for d in grupo); dir_ = max(d["box"][0] + d["box"][2] for d in grupo)
    centro = (esq + dir_) / 2 if dir_ - esq <= jan else best["cx"]
    rot_extra = ""
    bx, _, bw, _ = best["box"]
    if bw > jan * 0.8:   # objeto do tamanho da janela (moto com piloto, carro de perto): mira em quem está nele
        dentro = [c for c in rostos_cx if bx - bw * 0.3 <= c <= bx + bw * 1.3]
        if dentro:
            centro = min(dentro, key=lambda c: abs(c - best["cx"])); rot_extra = " + rosto"
    rot = best["classe"] + rot_extra + (f" ({len(grupo)})" if len(grupo) > 1 and dir_ - esq <= jan else "") + motivo_extra
    # acompanha: o mesmo objeto nos quadros 0 e 2
    if len(cs) >= 3:
        trilha = []
        for k in (0, 2):
            prox = [d for d in cs[k] if d["coco"] == best["coco"] and abs(d["cx"] - best["cx"]) < max(best["box"][2], jan) * 0.9]
            trilha.append(min(prox, key=lambda d: abs(d["cx"] - best["cx"]))["cx"] if prox else best["cx"])
        if abs(trilha[1] - trilha[0]) > jan * 0.2 and len(grupo) == 1:
            return {"foco": [_foco_de_centro(trilha[0], jan, w), _foco_de_centro(trilha[1], jan, w)],
                    "layout": "cheio", "motivo": "acompanha " + rot, "_area": best["a"]}
    return {"foco": _foco_de_centro(centro, jan, w), "layout": "cheio", "motivo": rot, "_area": best["a"]}


def decidir(arquivo, ini, dur, crop=None, src_w=1920, src_h=1080, fala="", cena=""):
    import cv2
    iw, ih = (crop[0], crop[1]) if crop else (src_w, src_h)
    quadros = _quadros(arquivo, ini, dur, crop)
    if not quadros:
        return {"foco": 0.5, "layout": "cheio", "motivo": "sem quadros"}
    h, w = quadros[0].shape[:2]
    jan = w * (ih * 9 / 16) / iw
    if jan >= w:
        return {"foco": 0.5, "layout": "cheio", "motivo": "já vertical"}

    O, dets = _objetos(quadros)

    # 1) rostos: só vale rosto confiável E consistente (aparece em 2+ quadros ou confiança muito alta)
    por_quadro = [rostos(q) for q in quadros]

    def consistente(f, k):
        x, fw, _, conf = f
        if conf >= 0.9:
            return True
        cx = x + fw / 2
        outros = [g for j, fs in enumerate(por_quadro) if j != k for g in fs]
        return any(abs((g[0] + g[1] / 2) - cx) < max(fw, g[1]) * 1.6 for g in outros)

    validos = [[f for f in fs if f[3] >= 0.72 and consistente(f, k)] for k, fs in enumerate(por_quadro)]
    ordem = sorted(range(len(quadros)), key=lambda k: (abs(k - 1), -len(validos[k])))   # prefere o quadro do meio
    ordem = [k for k in ordem if validos[k]] or [1]
    fr = validos[ordem[0]] if ordem[0] < len(validos) else []
    # rosto "forte" = personagem em destaque na cena (confiante e não minúsculo)
    rosto_forte = any(f[3] >= 0.85 and f[1] >= w * 0.05 for f in fr)

    # 0) contexto da FALA: o que a narração cita e aparece no quadro ganha o foco,
    #    a não ser que seja um objeto pequeno de fundo numa cena dominada por um personagem
    if O is not None:
        alvo = O.assunto_da_fala(fala) - {"person"}
        if alvo:
            r = _foco_objetos(O, dets, alvo, jan, w, quadros[0].shape[0], " · citado na fala", area_min=0.012, conf_min=0.25,
                              rostos_cx=[f[0] + f[1] / 2 for f in fr])
            if r and not (rosto_forte and r["_area"] < 0.06):
                r.pop("_area", None)
                return r
        # contexto da CENA (tags/descrição) só quando não há personagem em destaque
        alvo_c = O.assunto_da_fala(cena) - {"person"}
        if alvo_c and not fr:
            r = _foco_objetos(O, dets, alvo_c, jan, w, quadros[0].shape[0], " · da cena", area_min=0.015, conf_min=0.3)
            if r:
                r.pop("_area", None)
                return r
    if fr:
        maior = max(a for _, _, a, _ in fr)
        fr = [f for f in fr if f[2] >= maior * 0.2]            # ignora rostinhos de fundo
        esq = min(x - fw * 0.25 for x, fw, _, _ in fr)
        dir_ = max(x + fw * 1.25 for x, fw, _, _ in fr)
        if len(fr) == 1:                                       # um rosto: se ele anda, a janela acompanha
            x, fw, _, _ = fr[0]
            c = x + fw / 2
            trilha = []
            for k in (0, 2):
                cand = [g for g in validos[k] if abs(g[0] + g[1] / 2 - c) < max(fw, g[1]) * 1.6]
                if cand:
                    g = min(cand, key=lambda g: abs(g[0] + g[1] / 2 - c))
                    trilha.append(g[0] + g[1] / 2)
                else:
                    trilha.append(c)
            if abs(trilha[1] - trilha[0]) > jan * 0.2:
                return {"foco": [_foco_de_centro(trilha[0], jan, w), _foco_de_centro(trilha[1], jan, w)],
                        "layout": "cheio", "motivo": "acompanha rosto"}
            return {"foco": _foco_de_centro(c, jan, w), "layout": "cheio", "motivo": "rosto (1)"}
        if dir_ - esq <= jan:
            return {"foco": _foco_de_centro((esq + dir_) / 2, jan, w), "layout": "cheio",
                    "motivo": f"rosto ({len(fr)})"}
        cs = sorted(x + fw / 2 for x, fw, _, _ in fr)
        return {"foco": [_foco_de_centro(cs[0], jan, w), _foco_de_centro(cs[-1], jan, w)], "layout": "cheio",
                "motivo": f"panorâmica ({len(fr)} rostos)"}

    # 2) sem rostos: objetos detectados (pessoa de corpo inteiro/de costas, carro, barco, animal...)
    if O is not None:
        r = _foco_objetos(O, dets, None, jan, w, quadros[0].shape[0], area_min=0.012)
        if r:
            r.pop("_area", None)
            return r

    # 3) nada detectado: movimento + saliência + centro
    sal = _norm(np.mean([_saliencia(q).sum(axis=0) for q in quadros], axis=0))
    mov = np.zeros(w, np.float32)
    for a, b in zip(quadros, quadros[1:]):
        d = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)).astype(np.float32)
        d[d < 18] = 0                                            # ignora ruído/compressão
        mov += d.sum(axis=0)
    # câmera em movimento (tudo mexe) não ajuda: só usa se o movimento estiver concentrado
    concentrado = mov.sum() > 0 and (np.sort(mov)[::-1][: int(w * 0.3)].sum() / mov.sum()) > 0.55
    centro = _norm(np.exp(-((np.arange(w) - w / 2) ** 2) / (2 * (w * 0.3) ** 2)))
    perfil = (0.5 * _norm(mov) if concentrado else 0) + 0.35 * sal + 0.15 * centro
    jw = int(round(jan))
    acum = np.concatenate([[0], np.cumsum(perfil)])
    capt = acum[jw:] - acum[:-jw]
    melhor = int(np.argmax(capt))
    return {"foco": round(float(melhor / (w - jw)), 3), "layout": "cheio",
            "motivo": "movimento" if concentrado else "destaque"}
