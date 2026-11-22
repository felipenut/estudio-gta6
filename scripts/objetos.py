"""Detector de objetos (YOLOX-S, OpenCV Zoo, licença Apache 2.0) para o enquadramento.

detectar(img_bgr, limiar=0.35) -> [{"classe": "carro", "coco": "car", "conf": 0.8, "box": (x, y, w, h)}, ...]
Também: assunto_da_fala(texto) -> set de classes citadas na narração ("lancha" -> barco, "viatura" -> carro...).
"""
from pathlib import Path
import numpy as np

MODELO = Path(__file__).resolve().parent.parent / "assets" / "modelos" / "object_detection_yolox_2022nov.onnx"
TAM = 640
_NET = {"net": None, "ok": None}

COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
        "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
        "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
        "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
        "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
        "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
        "hair drier", "toothbrush"]

# classe COCO -> (nome em português, peso como "assunto" da cena)
ASSUNTO = {"person": ("pessoa", 1.0), "car": ("carro", 0.9), "truck": ("caminhão", 0.85), "bus": ("ônibus", 0.7),
           "motorcycle": ("moto", 0.95), "bicycle": ("bicicleta", 0.7), "boat": ("barco", 0.9),
           "airplane": ("avião", 0.9), "train": ("trem", 0.6), "bird": ("ave", 0.75), "dog": ("cachorro", 0.85),
           "cat": ("gato", 0.8), "horse": ("cavalo", 0.8), "cow": ("vaca", 0.6), "bear": ("urso", 0.8),
           "cell phone": ("celular", 0.6), "tv": ("TV", 0.5), "refrigerator": ("geladeira", 0.45),
           "bed": ("cama", 0.35), "couch": ("sofá", 0.35), "bottle": ("garrafa", 0.3), "surfboard": ("prancha", 0.5),
           "sports ball": ("bola", 0.5), "skateboard": ("skate", 0.6), "umbrella": ("guarda-sol", 0.3),
           "handbag": ("bolsa", 0.35), "suitcase": ("mala", 0.4), "dining table": ("mesa", 0.25), "chair": ("cadeira", 0.2)}

# palavras da narração/tags -> classes que devem ganhar o foco
PALAVRAS = {
    "car": "carro carros viatura viaturas conversível conversivel esportivo picape caminhonete van fuga perseguição perseguicao racha corrida capotar capotado capotamento trânsito transito rodovia dirigir dirigindo carro-forte",
    "truck": "caminhão caminhao picape caminhonete carro-forte",
    "motorcycle": "moto motos motoqueiro motocross gangue empinando",
    "boat": "barco barcos lancha lanchas iate iates jet aerobarco navio caiaque pesca pescaria mar onda",
    "airplane": "avião aviao aviões jatinho hidroavião hidroaviao aeroporto",
    "bird": "ave aves pássaro passaro pássaros flamingo flamingos pelicano garça gaivota gaivotas",
    "dog": "cachorro cachorros cão",
    "person": "lucia jason casal personagem npc npcs pessoa pessoas gente pedestre pedestres multidão multidao influencer selfie dançando dancando dança policial policiais bandido assaltante",
    "cell phone": "celular celulares live selfie filmando",
    "tv": "tv televisão televisao comercial desenho documentário documentario",
    "refrigerator": "geladeira",
}
_PAL = {}
for cls, ws in PALAVRAS.items():
    for w in ws.split():
        _PAL.setdefault(w, set()).add(cls)


def _net():
    if _NET["ok"] is None:
        try:
            import cv2
            if not MODELO.exists():
                raise FileNotFoundError(MODELO)
            _NET["net"] = cv2.dnn.readNet(str(MODELO))
            _NET["ok"] = True
        except Exception as e:
            print(f"aviso: detector de objetos indisponível ({e}); usando só rostos/movimento")
            _NET["ok"] = False
    return _NET["net"] if _NET["ok"] else None


def _grade():
    g, s = [], []
    for st in (8, 16, 32):
        n = TAM // st
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        g.append(np.stack((xv, yv), 2).reshape(-1, 2)); s.append(np.full((n * n, 1), st))
    return np.concatenate(g).astype(np.float32), np.concatenate(s).astype(np.float32)


_G = None


def detectar(img, limiar=0.35):
    """img BGR -> lista de objetos (só classes de ASSUNTO), em coordenadas da imagem."""
    import cv2
    global _G
    net = _net()
    if net is None:
        return []
    h, w = img.shape[:2]
    r = min(TAM / h, TAM / w)
    pad = np.full((TAM, TAM, 3), 114, np.uint8)
    pad[: int(h * r), : int(w * r)] = cv2.resize(img, (int(w * r), int(h * r)))
    blob = cv2.cvtColor(pad, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32)
    net.setInput(blob)
    out = net.forward(net.getUnconnectedOutLayersNames())[0][0]
    if _G is None:
        _G = _grade()
    grid, stride = _G
    xy = (out[:, :2] + grid) * stride
    wh = np.exp(out[:, 2:4]) * stride
    scores = out[:, 4:5] * out[:, 5:]
    cls = scores.argmax(1)
    conf = scores[np.arange(len(cls)), cls]
    m = conf >= limiar
    if not m.any():
        return []
    xy, wh, cls, conf = xy[m], wh[m], cls[m], conf[m]
    caixas = np.concatenate([xy - wh / 2, wh], 1) / r
    idx = cv2.dnn.NMSBoxesBatched(caixas.tolist(), conf.tolist(), cls.tolist(), limiar, 0.45)
    res = []
    for i in np.array(idx).reshape(-1):
        nome = COCO[int(cls[i])]
        if nome not in ASSUNTO:
            continue
        x, y, bw, bh = caixas[i]
        x, y = max(0.0, x), max(0.0, y)
        bw, bh = min(w - x, bw), min(h - y, bh)
        if bw < 4 or bh < 4:
            continue
        res.append({"classe": ASSUNTO[nome][0], "coco": nome, "conf": round(float(conf[i]), 3),
                    "box": (float(x), float(y), float(bw), float(bh))})
    return res


def assunto_da_fala(texto):
    """Classes COCO citadas no texto do segmento/tags (para o contexto puxar o foco)."""
    import re
    out = set()
    for p in re.findall(r"[\wÀ-ú-]+", (texto or "").lower()):
        out |= _PAL.get(p, set())
    return out
