"""Efeitos de interface no estilo do HUD do GTA 6, por cima do vídeo (e por baixo da legenda).

Cada efeito do roteiro vira uma sequência curta de PNGs com transparência, do tamanho do elemento,
que o montar.py coloca na passada final com overlay. Os elementos entram deslizando rápido e param seco
(com um rastro leve), ficam parados e somem com um fade curto.

No roteiro, em cada segmento:
  "efeitos": [{"tipo": "estrelas", "qtd": 3}, {"tipo": "card", "titulo": "Veículo roubado", "sub": "SUV vermelha", "em": 0.4}]
Comuns a todos: "em" (s após o início do segmento, padrão 0.15), "dur" ou "ate" (s), "x"/"y" (0–1, centro do elemento),
"som" (nome de um som para trocar o automático, ou false).
Tipos: card, aviso, alerta, icone, fato, numero, estrelas, dinheiro, cronometro, moldura, pin, rota, seta, texto, titulo.
"""
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from comum import FONTES, FPS, H, W

AMARELO = (255, 214, 10)
ROSA = (255, 46, 160)
BRANCO = (255, 255, 255)
PRETO = (0, 0, 0)
VERDE = (60, 230, 120)
VERMELHO = (235, 40, 60)
LARANJA = (255, 150, 20)
CINZA = (120, 120, 130)
PAINEL = (12, 12, 16, 222)
CORES = {"amarelo": AMARELO, "rosa": ROSA, "branco": BRANCO, "verde": VERDE, "vermelho": VERMELHO, "laranja": LARANJA}

TIPOS = ("card", "aviso", "alerta", "icone", "fato", "numero", "estrelas", "dinheiro", "cronometro", "moldura",
         "pin", "rota", "seta", "texto", "titulo")
SOM_PADRAO = {"card": "pop", "texto": "pop", "fato": "pop", "titulo": "pop", "pin": "pop", "moldura": "pop",
              "aviso": "notificacao", "alerta": "notificacao", "dinheiro": "dinheiro", "cronometro": "relogio",
              "numero": "whoosh", "seta": "whoosh", "rota": "whoosh", "estrelas": "pop"}
POSICAO = {"card": (0.5, 0.2), "aviso": (0.5, 0.17), "alerta": (0.5, 0.2), "icone": (0.5, 0.2), "fato": (0.2, 0.09),
           "numero": (0.5, 0.27), "estrelas": (0.5, 0.11), "dinheiro": (0.5, 0.18), "cronometro": (0.82, 0.13),
           "pin": (0.5, 0.4), "seta": (0.5, 0.3), "texto": (0.5, 0.2), "titulo": (0.5, 0.16)}
ENTRADA, SAIDA = 0.24, 0.16
MARGEM = 90                       # espaço no quadro do elemento para ele deslizar ao entrar


# ---------------------------------------------------------------- fontes
_FONTES = {}


def _fonte(nome, tam, eixos=None):
    chave = (nome, tam, tuple(eixos or ()))
    if chave not in _FONTES:
        f = None
        for candidato in (nome, "Bangers-Regular.ttf"):
            try:
                f = ImageFont.truetype(str(FONTES / candidato), tam)
                break
            except OSError:
                continue
        if f is None:
            f = ImageFont.load_default()
        if eixos:
            try:
                f.set_variation_by_axes(list(eixos))
            except Exception:       # FreeType sem suporte a fonte variável: fica com o peso padrão
                pass
        _FONTES[chave] = f
    return _FONTES[chave]


def hud(tam, peso=820):
    """Fonte condensada e pesada, parecida com a do HUD do jogo."""
    return _fonte("Roboto-Variavel.ttf", tam, (peso, 75))


def grossa(tam):
    return _fonte("ArchivoBlack-Regular.ttf", tam)


# ---------------------------------------------------------------- utilidades de animação e desenho
def ease_out_expo(x):
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * max(0.0, x))


def ease_out_back(x, s=1.4):
    x = min(1.0, max(0.0, x)) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def cor(v, padrao=AMARELO):
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return tuple(int(c) for c in v[:3])
    if isinstance(v, str):
        if v.lower() in CORES:
            return CORES[v.lower()]
        h = v.lstrip("#")
        if len(h) == 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                pass
    return padrao


def medir(f, texto):
    x0, y0, x1, y1 = f.getbbox(texto)
    return x1 - x0, y1 - y0, x0, y0


def texto_com_contorno(d, xy, texto, f, preench=BRANCO, contorno=0, cor_contorno=PRETO, anchor="la"):
    d.text(xy, texto, font=f, fill=preench, stroke_width=contorno, stroke_fill=cor_contorno, anchor=anchor)


def com_sombra(img, raio=16, alpha=150, desloc=(0, 8)):
    """Sombra projetada suave atrás do elemento (fica dentro da mesma imagem)."""
    m = 36
    base = Image.new("RGBA", (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0))
    sombra = Image.new("RGBA", base.size, (0, 0, 0, 0))
    a = img.getchannel("A").point(lambda v: v * alpha // 255)
    preto = Image.new("RGBA", img.size, (0, 0, 0, 255))
    preto.putalpha(a)
    sombra.paste(preto, (m + desloc[0], m + desloc[1]))
    sombra = sombra.filter(ImageFilter.GaussianBlur(raio))
    base.alpha_composite(sombra)
    base.alpha_composite(img, (m, m))
    return base


def painel(w, h, barra=None, raio=14):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), raio, fill=PAINEL)
    if barra:
        d.rounded_rectangle((0, 0, 12, h - 1), raio // 2, fill=barra + (255,))
    return img


def estrela_pts(cx, cy, r, ri=None):
    ri = ri or r * 0.45
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else ri
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


def multiplicar_alpha(img, fator):
    if fator >= 0.999:
        return img
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * max(0.0, fator))))
    return img


def escalar(img, s):
    if abs(s - 1) < 0.004:
        return img
    w, h = max(1, int(img.width * s)), max(1, int(img.height * s))
    return img.resize((w, h), Image.BICUBIC)


# ---------------------------------------------------------------- os elementos (cada um: imagem do elemento no instante t)
class Elemento:
    """Base: desenha(t) -> imagem RGBA do elemento parado; a entrada/saída é aplicada por fora."""
    direcao = (0, -1)          # de onde entra: (0,-1) = de cima, (-1,0) = da esquerda
    pop = False                # entra crescendo em vez de deslizar

    def __init__(self, e, dur):
        self.e, self.dur = e, dur

    def desenha(self, t):
        raise NotImplementedError


class Card(Elemento):
    direcao = (-1, 0)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        c = cor(e.get("cor"), AMARELO)
        titulo, sub = str(e.get("titulo", "")).upper(), str(e.get("sub", "")).upper()
        ft, fs = hud(40, 760), hud(76)
        wt, ht, _, _ = medir(ft, titulo or " ")
        ws, hs, _, _ = medir(fs, sub or " ")
        w = max(wt, ws) + 84
        h = (ht + 22 if titulo else 0) + hs + 56
        img = painel(w, h, barra=c)
        d = ImageDraw.Draw(img)
        y = 26
        if titulo:
            d.text((40, y), titulo, font=ft, fill=c, anchor="lt")
            y += ht + 22
        d.text((40, y), sub, font=fs, fill=BRANCO, anchor="lt")
        self.img = com_sombra(img)

    def desenha(self, t):
        return self.img


class Texto(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        c = cor(e.get("cor"), AMARELO)
        txt = str(e.get("texto", "")).upper()
        f = hud(int(e.get("tamanho", 64)))
        w, h, _, _ = medir(f, txt or " ")
        img = Image.new("RGBA", (w + 76, h + 50), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, img.width - 1, img.height - 1), img.height // 2, fill=PAINEL, outline=c + (255,), width=5)
        d.text((img.width // 2, img.height // 2), txt, font=f, fill=BRANCO, anchor="mm")
        self.img = com_sombra(img)

    def desenha(self, t):
        return self.img


class Titulo(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        c = cor(e.get("cor"), AMARELO)
        txt = str(e.get("texto", "")).upper()
        f = hud(int(e.get("tamanho", 128)), 900)
        w, h, _, _ = medir(f, txt or " ")
        img = Image.new("RGBA", (w + 60, h + 70), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((30, 10), txt, font=f, fill=BRANCO, anchor="lt", stroke_width=6, stroke_fill=PRETO)
        d.rectangle((30, h + 40, 30 + int(w * 0.55), h + 54), fill=c + (255,))
        # leve inclinação, como os títulos do jogo
        img = img.transform(img.size, Image.AFFINE, (1, 0.12, -0.12 * img.height / 2, 0, 1, 0), Image.BICUBIC)
        self.img = com_sombra(img, alpha=120)

    def desenha(self, t):
        return self.img


class Aviso(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        c = cor(e.get("cor"), AMARELO)
        txt = str(e.get("texto", "")).upper()
        f = hud(54)
        w, h, _, _ = medir(f, txt or " ")
        alt = h + 48
        img = Image.new("RGBA", (w + alt + 70, alt), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, img.width - 1, alt - 1), 12, fill=PAINEL, outline=c + (255,), width=4)
        # triângulo de alerta
        a, cx, cy = alt * 0.62, alt * 0.62, alt / 2
        d.polygon([(cx, cy - a / 2), (cx + a / 2, cy + a / 2.4), (cx - a / 2, cy + a / 2.4)], fill=c + (255,))
        d.text((cx, cy + a * 0.06), "!", font=hud(int(a * 0.62), 900), fill=PRETO, anchor="mm")
        d.text((alt + 26, alt // 2), txt, font=f, fill=BRANCO, anchor="lm")
        self.img = com_sombra(img)

    def desenha(self, t):
        return self.img


class Icone(Elemento):
    pop = True

    def __init__(self, e, dur):
        super().__init__(e, dur)
        simb = e.get("simbolo", "alerta" if e.get("tipo") == "alerta" else "check")
        fundo = {"check": VERDE, "cifrao": VERDE, "x": VERMELHO, "proibido": VERMELHO, "alerta": VERMELHO}.get(simb, AMARELO)
        fundo = cor(e.get("cor"), fundo)
        n = int(e.get("tamanho", 170))
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, n - 5, n - 5), fill=fundo + (255,), outline=BRANCO + (255,), width=max(4, n // 26))
        lw, m = max(8, n // 11), n * 0.3
        if simb == "check":
            d.line([(m, n * 0.52), (n * 0.44, n - m), (n - m * 0.85, m * 1.05)], fill=BRANCO, width=lw, joint="curve")
        elif simb == "x":
            d.line([(m, m), (n - m, n - m)], fill=BRANCO, width=lw)
            d.line([(n - m, m), (m, n - m)], fill=BRANCO, width=lw)
        elif simb == "proibido":
            d.ellipse((m * 0.7, m * 0.7, n - m * 0.7, n - m * 0.7), outline=BRANCO, width=lw)
            d.line([(m * 0.95, n - m * 0.95), (n - m * 0.95, m * 0.95)], fill=BRANCO, width=lw)
        else:
            d.text((n / 2, n / 2 + n * 0.02), "$" if simb == "cifrao" else "!", font=hud(int(n * 0.62), 900),
                   fill=BRANCO, anchor="mm")
        self.img = com_sombra(img, alpha=120)

    def desenha(self, t):
        s = 1 + 0.05 * math.sin(max(0.0, t - ENTRADA) * 7)        # pulsa devagar
        return escalar(self.img, s)


class Fato(Elemento):
    direcao = (-1, 0)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.n, self.total = int(e.get("n", 1)), max(1, int(e.get("total", 5)))
        self.c = cor(e.get("cor"), AMARELO)

    def desenha(self, t):
        fp, fn = hud(38, 760), hud(84, 900)
        w, h = 330, 170
        img = painel(w, h, barra=self.c)
        d = ImageDraw.Draw(img)
        d.text((40, 22), "FATO", font=fp, fill=self.c, anchor="lt")
        d.text((40, 62), f"{self.n}/{self.total}", font=fn, fill=BRANCO, anchor="lt")
        prog = (self.n - 1 + min(1.0, ease_out_expo(t / 0.6))) / self.total
        d.rounded_rectangle((40, h - 26, w - 30, h - 16), 5, fill=(255, 255, 255, 60))
        d.rounded_rectangle((40, h - 26, 40 + int((w - 70) * prog), h - 16), 5, fill=self.c + (255,))
        return com_sombra(img)


class Numero(Elemento):
    pop = True

    def __init__(self, e, dur):
        super().__init__(e, dur)
        txt = str(e.get("n", e.get("texto", "1")))
        f = grossa(int(e.get("tamanho", 400)))
        w, h, x0, y0 = medir(f, txt)
        pad = 40
        texto = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        ImageDraw.Draw(texto).text((pad - x0, pad - y0), txt, font=f, fill=255)
        degr = Image.new("RGBA", texto.size)
        dd = ImageDraw.Draw(degr)
        for y in range(texto.height):              # degradê amarelo -> laranja
            k = y / max(1, texto.height - 1)
            dd.line([(0, y), (texto.width, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(AMARELO, LARANJA)) + (255,))
        contorno = Image.new("RGBA", texto.size, PRETO + (0,))
        borda = texto.filter(ImageFilter.MaxFilter(25))
        contorno.putalpha(borda)
        degr.putalpha(texto)
        contorno.alpha_composite(degr)
        legenda = str(e.get("sub", "")).upper()
        if legenda:
            fs = hud(78)
            ws, hs, _, _ = medir(fs, legenda)
            novo = Image.new("RGBA", (max(contorno.width, ws + 40), contorno.height + hs + 20), (0, 0, 0, 0))
            novo.alpha_composite(contorno, ((novo.width - contorno.width) // 2, 0))
            ImageDraw.Draw(novo).text((novo.width // 2, contorno.height - 6), legenda, font=fs, fill=BRANCO,
                                      anchor="mt", stroke_width=7, stroke_fill=PRETO)
            contorno = novo
        self.img = com_sombra(contorno, raio=20, alpha=170)

    def desenha(self, t):
        return self.img


class Estrelas(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.total = max(1, min(6, int(e.get("total", 5))))
        self.qtd = max(0, min(self.total, int(e.get("qtd", 3))))
        self.intervalo = 0.2

    def desenha(self, t):
        r, gap = 50, 26
        w = self.total * (2 * r) + (self.total - 1) * gap + 40
        img = Image.new("RGBA", (w, 2 * r + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for k in range(self.total):
            cx, cy = 20 + r + k * (2 * r + gap), 30 + r
            acesa_em = ENTRADA + k * self.intervalo
            if k < self.qtd and t >= acesa_em:
                s = 1 + 0.35 * max(0.0, 1 - (t - acesa_em) / 0.14)      # pequeno "pop" ao acender
                d.polygon(estrela_pts(cx, cy, r * s), fill=BRANCO, outline=PRETO, width=6)
                d.polygon(estrela_pts(cx, cy, r * s * 0.62), fill=AMARELO)
            else:
                d.polygon(estrela_pts(cx, cy, r), fill=(40, 40, 46, 170), outline=(255, 255, 255, 150), width=5)
        return com_sombra(img, alpha=120)

    def acendimentos(self):
        return [ENTRADA + k * self.intervalo for k in range(self.qtd)]


def _dinheiro(v):
    return "$" + f"{abs(int(round(v))):,}".replace(",", ".")


class Dinheiro(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.de, self.para = float(e.get("de", 0)), float(e.get("para", 1000))
        self.sobe = self.para >= self.de
        self.c = VERDE if self.sobe else VERMELHO
        self.f, self.fd = hud(104, 900), hud(46, 800)
        maior = max(abs(self.de), abs(self.para))
        self.w = medir(self.f, _dinheiro(maior) + "0")[0] + 90

    def desenha(self, t):
        k = ease_out_expo(max(0.0, t - ENTRADA) / 1.1)
        valor = self.de + (self.para - self.de) * k
        h = 196
        img = painel(self.w, h, barra=self.c)
        d = ImageDraw.Draw(img)
        delta = ("+ " if self.sobe else "− ") + _dinheiro(self.para - self.de)
        d.text((44, 24), delta, font=self.fd, fill=self.c, anchor="lt")
        d.text((44, 80), _dinheiro(valor), font=self.f, fill=BRANCO, anchor="lt")
        return com_sombra(img)


class Cronometro(Elemento):
    pop = True

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.de = max(1, int(e.get("de", 60)))
        self.c = cor(e.get("cor"), AMARELO)

    def desenha(self, t):
        n, esp = 240, 18
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, n - 7, n - 7), fill=PAINEL)
        d.arc((esp, esp, n - esp, n - esp), 0, 360, fill=(255, 255, 255, 50), width=esp)
        decorrido = max(0.0, t - ENTRADA)
        resto = max(0.0, self.de - decorrido)
        frac = resto / self.de
        if frac > 0:
            d.arc((esp, esp, n - esp, n - esp), -90, -90 + 360 * frac, fill=self.c + (255,), width=esp)
        d.text((n / 2, n / 2), str(int(math.ceil(resto))), font=grossa(92), fill=BRANCO, anchor="mm")
        return com_sombra(img, alpha=120)


class Seta(Elemento):
    pop = True

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.dir = e.get("dir", "baixo")
        n = int(e.get("tamanho", 230))
        img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pts = [(n * 0.5, n * 0.06), (n * 0.94, n * 0.5), (n * 0.68, n * 0.5), (n * 0.68, n * 0.94),
               (n * 0.32, n * 0.94), (n * 0.32, n * 0.5), (n * 0.06, n * 0.5)]        # apontando para cima
        d.polygon(pts, fill=cor(e.get("cor"), AMARELO) + (255,), outline=PRETO, width=9)
        giro = {"cima": 0, "frente": 0, "esquerda": 90, "baixo": 180, "direita": -90}.get(self.dir, 180)
        self.img = com_sombra(img.rotate(giro, resample=Image.BICUBIC), alpha=130)
        self.vetor = {"cima": (0, -1), "frente": (0, -1), "esquerda": (-1, 0), "baixo": (0, 1), "direita": (1, 0)}.get(self.dir, (0, 1))

    def desenha(self, t):
        return self.img

    def deslocamento(self, t):         # empurrãozinho na direção da seta
        k = 14 * abs(math.sin(max(0.0, t - ENTRADA) * 6))
        return int(self.vetor[0] * k), int(self.vetor[1] * k)


class Pin(Elemento):
    direcao = (0, -1)

    def __init__(self, e, dur):
        super().__init__(e, dur)
        c = cor(e.get("cor"), AMARELO)
        txt = str(e.get("texto", "")).upper()
        r = 46
        pino = Image.new("RGBA", (2 * r + 12, 3 * r + 12), (0, 0, 0, 0))
        d = ImageDraw.Draw(pino)
        cx, cy = r + 6, r + 6
        d.polygon([(cx - r * 0.72, cy + r * 0.62), (cx, cy + r * 2.1), (cx + r * 0.72, cy + r * 0.62)], fill=c + (255,),
                  outline=PRETO, width=5)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c + (255,), outline=PRETO, width=5)
        d.ellipse((cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38), fill=BRANCO)
        etiqueta = None
        if txt:
            f = hud(48)
            w, h, _, _ = medir(f, txt)
            etiqueta = Image.new("RGBA", (w + 50, h + 36), (0, 0, 0, 0))
            de = ImageDraw.Draw(etiqueta)
            de.rounded_rectangle((0, 0, etiqueta.width - 1, etiqueta.height - 1), 10, fill=PAINEL, outline=c + (255,), width=4)
            de.text((etiqueta.width // 2, etiqueta.height // 2), txt, font=f, fill=BRANCO, anchor="mm")
        largura = pino.width + (etiqueta.width + 18 if etiqueta else 0)
        img = Image.new("RGBA", (largura, max(pino.height, etiqueta.height if etiqueta else 0)), (0, 0, 0, 0))
        img.alpha_composite(pino, (0, 0))
        if etiqueta:
            img.alpha_composite(etiqueta, (pino.width + 18, int(cy - etiqueta.height / 2)))
        self.img = com_sombra(img, alpha=130)
        # a ponta do pino fica no ponto (x, y) pedido, e não o centro da imagem
        self.ancora = (36 + cx, 36 + int(cy + r * 2.1))

    def desenha(self, t):
        return self.img


class Moldura(Elemento):
    pop = True

    def __init__(self, e, dur):
        super().__init__(e, dur)
        self.w, self.h = int(float(e.get("w", 0.5)) * W), int(float(e.get("h", 0.2)) * H)
        self.c = cor(e.get("cor"), AMARELO)

    def desenha(self, t):
        m = 40
        img = Image.new("RGBA", (self.w + 2 * m, self.h + 2 * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        k = ease_out_expo(t / ENTRADA)
        abre = int(30 * (1 - k))                 # os cantos fecham até o lugar
        x0, y0, x1, y1 = m - abre, m - abre, m + self.w + abre, m + self.h + abre
        L, esp = int(min(self.w, self.h) * 0.22) + 20, 11
        for (ax, ay, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            for cor_, larg in ((PRETO + (200,), esp + 8), (self.c + (255,), esp)):
                d.line([(ax, ay + sy * L), (ax, ay), (ax + sx * L, ay)], fill=cor_, width=larg, joint="curve")
        return img


class Rota(Elemento):
    pop = False

    def __init__(self, e, dur):
        super().__init__(e, dur)
        pts = e.get("pontos") or [[0.3, 0.6], [0.5, 0.45], [0.7, 0.35]]
        self.pts = [(float(x) * W, float(y) * H) for x, y in pts]
        xs, ys = [p[0] for p in self.pts], [p[1] for p in self.pts]
        m = 40
        self.x0, self.y0 = min(xs) - m, min(ys) - m
        self.size = (int(max(xs) - self.x0 + m), int(max(ys) - self.y0 + m))
        self.c = cor(e.get("cor"), VERDE)
        self.comp = [math.dist(a, b) for a, b in zip(self.pts, self.pts[1:])]

    def desenha(self, t):
        img = Image.new("RGBA", self.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        alvo = sum(self.comp) * ease_out_expo(t / 0.9)
        feito, desenhar = 0.0, [self._local(self.pts[0])]
        for (a, b), comp in zip(zip(self.pts, self.pts[1:]), self.comp):
            if feito + comp <= alvo:
                desenhar.append(self._local(b))
                feito += comp
            else:
                k = (alvo - feito) / comp if comp else 0
                desenhar.append(self._local((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)))
                break
        if len(desenhar) > 1:
            d.line(desenhar, fill=PRETO + (190,), width=26, joint="curve")
            d.line(desenhar, fill=self.c + (255,), width=15, joint="curve")
        px, py = desenhar[-1]
        d.ellipse((px - 16, py - 16, px + 16, py + 16), fill=BRANCO, outline=PRETO, width=4)
        return img

    def _local(self, p):
        return p[0] - self.x0, p[1] - self.y0


CLASSES = {"card": Card, "texto": Texto, "titulo": Titulo, "aviso": Aviso, "alerta": Icone, "icone": Icone,
           "fato": Fato, "numero": Numero, "estrelas": Estrelas, "dinheiro": Dinheiro, "cronometro": Cronometro,
           "seta": Seta, "pin": Pin, "moldura": Moldura, "rota": Rota}


# ---------------------------------------------------------------- render das sequências
def _quadro(el, t, dur):
    """Elemento no instante t com entrada (desliza/pop + rastro) e saída (fade)."""
    img = el.desenha(t)
    k = ease_out_expo(t / ENTRADA)
    alpha = min(1.0, t / (ENTRADA * 0.6)) * min(1.0, max(0.0, (dur - t) / SAIDA))
    dx = dy = 0
    if el.pop:
        s = 1.45 - 0.45 * k if t < ENTRADA else 1.0
        img = escalar(img, s)
    else:
        dx, dy = el.direcao[0] * int(MARGEM * (1 - k)), el.direcao[1] * int(MARGEM * (1 - k))
    if hasattr(el, "deslocamento"):
        ox, oy = el.deslocamento(t)
        dx, dy = dx + ox, dy + oy
    return multiplicar_alpha(img, alpha), (dx, dy), k


def renderizar(efeitos, pasta):
    """efeitos: [{"tipo", "t0", "dur", ...}] em tempo do vídeo. Devolve [{"padrao", "t0", "x", "y", "quadros"}]
    para o overlay e a lista de sons [(nome, t, volume)]."""
    pasta = Path(pasta)
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True, exist_ok=True)
    saidas, sons = [], []
    for i, e in enumerate(efeitos):
        tipo = e.get("tipo")
        if tipo not in CLASSES:
            print(f"aviso: efeito '{tipo}' desconhecido, ignorado (use: {', '.join(TIPOS)})")
            continue
        dur = max(0.6, float(e["dur"]))
        el = CLASSES[tipo](e, dur)
        n = max(1, int(round(dur * FPS)))
        # tamanho fixo do quadro: o maior que o elemento chega a ter, mais a folga para deslizar
        amostras = [el.desenha(t) for t in (0, ENTRADA, min(dur, 1.4), dur * 0.99)]
        if el.pop:
            amostras.append(escalar(amostras[0], 1.45))
        cw = max(a.width for a in amostras) + 2 * MARGEM
        ch = max(a.height for a in amostras) + 2 * MARGEM
        # centro na tela
        if tipo == "moldura":
            cx = (float(e.get("x", 0.5))) * W
            cy = (float(e.get("y", 0.4))) * H
        elif tipo == "rota":
            cx, cy = el.x0 + el.size[0] / 2, el.y0 + el.size[1] / 2
        else:
            px, py = POSICAO.get(tipo, (0.5, 0.2))
            cx, cy = float(e.get("x", px)) * W, float(e.get("y", py)) * H
        ancora = getattr(el, "ancora", None)
        d = pasta / f"e{i:02d}"
        d.mkdir()
        for q in range(n):
            t = q / FPS
            img, (dx, dy), k = _quadro(el, t, dur)
            quadro = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            if ancora:
                ox, oy = cw // 2 - ancora[0], ch // 2 - ancora[1]
            else:
                ox, oy = (cw - img.width) // 2, (ch - img.height) // 2
            if not el.pop and k < 0.98:      # rastro de movimento durante a entrada
                for passo, a_r in ((0.5, 0.18), (0.28, 0.32)):
                    quadro.alpha_composite(multiplicar_alpha(img, a_r),
                                           (ox + int(dx + el.direcao[0] * MARGEM * passo * (1 - k)),
                                            oy + int(dy + el.direcao[1] * MARGEM * passo * (1 - k))))
            quadro.alpha_composite(img, (max(0, min(cw - img.width, ox + dx)), max(0, min(ch - img.height, oy + dy))))
            quadro.save(d / f"{q:04d}.png", compress_level=1)
        x, y = int(round(cx - cw / 2)), int(round(cy - ch / 2))
        saidas.append({"padrao": str(d / "%04d.png"), "t0": round(float(e["t0"]), 3), "x": x, "y": y, "quadros": n})
        som = e.get("som", SOM_PADRAO.get(tipo))
        if tipo in ("icone", "alerta") and "som" not in e:
            som = "notificacao" if e.get("simbolo", "alerta" if tipo == "alerta" else "check") in ("alerta", "x", "proibido") else "pop"
        if som:
            if tipo == "estrelas" and "som" not in e:
                sons += [("pop", e["t0"] + t, 0.9) for t in el.acendimentos()]
            elif tipo == "cronometro" and "som" not in e:
                sons += [("relogio", e["t0"] + ENTRADA + s, 0.6) for s in range(int(dur - ENTRADA - 0.1) + 1)]
            else:
                sons.append((str(som), e["t0"] + 0.02, 1.0))
    return saidas, sons


def planejar(rot, tseg, total):
    """Converte os "efeitos" dos segmentos em eventos com tempo absoluto."""
    eventos = []
    for i, s in enumerate(rot.get("segmentos", [])):
        if i not in tseg:
            continue
        a, b = tseg[i]
        for e in s.get("efeitos") or []:
            if not isinstance(e, dict) or not e.get("tipo"):
                continue
            t0 = a + float(e.get("em", 0.15))
            if "ate" in e:
                fim = a + float(e["ate"])
            elif "dur" in e:
                fim = t0 + float(e["dur"])
            else:
                padrao = {"cronometro": 3.2, "rota": 2.4, "numero": 1.6}.get(e["tipo"], 2.4)
                fim = min(t0 + padrao, max(b, t0 + 1.2))
            fim = min(fim, total - 0.05)
            if fim - t0 >= 0.5:
                eventos.append({**e, "t0": round(t0, 3), "dur": round(fim - t0, 3)})
    return eventos
