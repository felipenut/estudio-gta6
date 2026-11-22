"""Cut one candidate into a finished vertical clip.

1080x1920, 30 fps, word-by-word burned captions (slurs and swears masked), hook box in the first seconds,
loudness normalised to -14 LUFS. Writes jobs/<id>/edits/clip_<n>.mp4 + .json (metadata for check.py).
Edição para retenção (--edicao, padrão "pausas,zoom,voz"): tira pausas mortas entre falas (nunca a ação sem fala
nem o pico), zoom leve alternado a cada ~4 s e mais forte no pico (layouts blur/fill), limpeza leve de voz e,
com "loop", emenda o fim no começo. Legenda dentro da zona segura do TikTok/Reels/Shorts.

usage: python cut.py jobs/<id> --pick 1 [--layout fill|blur|facecam|react] [--hook "TEXT"]
                     [--cam auto|x:y:w:h] [--title "TEXT" --title-style box|outline --title-secs 4] [--captions word|bubble|none]
                     [--edicao pausas,zoom,voz,loop | --edicao nenhuma]
"""
from time import perf_counter
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import executar_render, load_json, renderizar_com_progresso, save_json, tool

W, H = 1080, 1920


def ts(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


import re as _re
_SLURS = _re.compile(r"\b(nigg\w*|n[i1]gg?a\w*|f[a@]gg?\w*|retard\w*|tranny\w*|chink\w*|spic\w*|kike\w*|viad[oa]\w*|macac[oa]s?)\b", _re.I)


_SWEARS = _re.compile(r"\b(fuck\w*|motherfuck\w*|shit\w*|bitch\w*|cunt\w*|dick\w*|pussy\w*|asshole\w*|bastard\w*|whore\w*|slut\w*|porra\w*|caralh\w*|merda\w*|put[ao]\w*|fdp|buceta\w*|cacete)\b", _re.I)


def _mask(m):
    w = m.group(0)
    return w[0] + '*' * (len(w) - 1)


def clean(s, profanity=False):
    """Slurs are always masked (n-word -> n****); hard swears too unless profanity=True."""
    s = _SLURS.sub(_mask, s)
    return s if profanity else _SWEARS.sub(_mask, s)


def esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def wrap(text, width):
    lines, cur = [], ''
    for wd in text.split():
        if cur and len(cur) + 1 + len(wd) > width:
            lines.append(cur); cur = wd
        else:
            cur = (cur + ' ' + wd).strip()
    return lines + ([cur] if cur else [])


def build_ass(words, s0, e0, hook, cap_y, title=None, caps='word', profanity=False):
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,92,&H00FFFFFF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,90,150,0,1
Style: Hook,Arial Black,68,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,170,1
Style: TitleBox,Arial Black,66,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1
Style: TitleOut,Arial Black,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,9,2,8,50,50,0,1
Style: Bubble,Arial,58,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,0,5,90,150,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    ws = [dict(w, w=clean(w["w"], profanity)) for w in words if s0 <= w["s"] < e0 and w["w"]]
    # groups of up to 3 words, break on punctuation or pauses
    groups, cur = [], []
    for w in ws:
        if cur and (len(cur) == 3 or w["s"] - cur[-1]["e"] > 0.6 or cur[-1]["w"][-1:] in ".?!,"):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    hook_end = 4.0 if hook else 0
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.4
        g_end = min(g_end, g[-1]["e"] + 0.8)
        for k, w in enumerate(g):
            a = w["s"] - s0; b = (g[k + 1]["s"] - s0) if k + 1 < len(g) else g_end - s0
            if b <= a:
                continue
            parts = []
            for j, x in enumerate(g):
                t = esc(x["w"].upper())
                parts.append("{\\c&H0000E5FF&}" + t + "{\\c&H00FFFFFF&}" if j == k else t)
            pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
            if caps == 'bubble':
                if k == 0:
                    txt = esc(' '.join(x['w'] for x in g)).strip()
                    txt = txt[:1].upper() + txt[1:]
                    ev.append(f"Dialogue: 0,{ts(a)},{ts(g_end - s0)},Bubble,,0,0,0,,{{\\pos({CAP_X},{cap_y})}}{pop}{txt}")
                continue
            ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{{\\pos({CAP_X},{cap_y})}}{pop}{' '.join(parts)}")
    if title:  # reaction title: (style, text, y, seconds)
        st, text, ty, secs, *opcoes = title
        tamanho = opcoes[0] if opcoes else 66
        end = (e0 - s0) if secs <= 0 else secs
        lines = wrap(esc(text), max(12, int(26 * 66 / tamanho)))
        body = '\\N'.join(lines)
        if st == 'box':
            ev.append(f"Dialogue: 2,{ts(0)},{ts(end)},TitleOut,,0,0,0,,{{\\pos({W // 2},{ty})\\an5\\fs{tamanho}}}{body}")
        else:
            ev.append(f"Dialogue: 2,{ts(0)},{ts(end)},TitleOut,,0,0,0,,{{\\pos({W // 2},{ty})\\an5\\fs{tamanho}}}{body}")
        hook = ''
    if hook:
        ev.append(f"Dialogue: 1,{ts(0)},{ts(hook_end)},Hook,,0,0,0,,{{\\fad(0,180)\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)}}{esc(hook)}")
    return hdr + "\n".join(ev) + "\n"


# Zona segura (TikTok/Reels/Shorts): a descrição e os botões ocupam ~20% de baixo e ~130 px da direita.
CAP_Y = {"fill": 1380, "blur": 1420, "facecam": 1120, "react": 1440}
CAP_X = 520
ZONA_SEGURA = {"topo": 220, "baixo": 1500, "direita": 950}
TOP = 730  # react layout: face panel height = seam y (even)
GAME_H = H - TOP  # 1190


def even(n):
    return int(n) // 2 * 2


def video_filter(layout, cam, ass, band=None, cam_side='right', src=None, game_x=None, face_expr=None, posicao_jogo=50):
    """Layout + burned-caption filter graph ending in [vo]. Reused by translate.py."""
    if layout == "fill":
        v = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:force_divisible_by=2,"
             f"crop={W}:{H}[v]")
    elif layout == "blur":
        # O fundo é desfocado: calculá-lo em 1/4 da resolução mantém o efeito e reduz o custo.
        v = (f"[0:v]split[a][b];[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase:"
             f"force_divisible_by=2,crop={W // 4}:{H // 4},boxblur=6:2,"
             f"eq=brightness=-0.08,scale={W}:{H}[bg];"
             f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2-80[v]")
    elif layout == 'react':
        sw, sh = src
        if face_expr:  # tracked face crop (no cam frame)
            cw, chh, ex, ey = face_expr
            top = f"crop={cw}:{chh}:{ex}:{ey}"
        else:
            x, y, w, h = map(float, cam.split(':'))
            cw, chh = even(sw * w), even(sh * h)
            top = f"crop={cw}:{chh}:{even(sw * x)}:{even(sh * y)}"
        gw = even(sw * GAME_H / sh) if sw * GAME_H / sh >= W else W
        gx = game_x if game_x is not None else ((gw - W) if cam_side == 'left' else 0)
        v = (f"[0:v]split[a][b];[a]{top},scale={W}:{TOP}:force_original_aspect_ratio=increase,crop={W}:{TOP},setsar=1[cam];"
             f"[b]scale={gw}:{GAME_H},crop={W}:{GAME_H}:{even(gx)}:0,setsar=1[game];[cam][game]vstack[v]")
    else:
        x, y, w, h = map(float, cam.split(":"))
        altura_cam = even(H * 0.38)
        altura_jogo = H - altura_cam
        v = (f"[0:v]split[a][b];[a]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={W}:{altura_cam}:force_original_aspect_ratio=increase,"
             f"crop={W}:{altura_cam},setsar=1[cam];[b]scale={W}:{altura_jogo}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={W}:{altura_jogo}:(iw-ow)*{posicao_jogo}/100:(ih-oh)/2,setsar=1[game];[cam][game]vstack[v]")
    if band:
        y0, bh, secs, *cores = band
        cor = cores[0] if cores else '0xB92F78'
        en = f":enable='lte(t,{secs})'" if secs > 0 else ''
        v = v[:-3] + f"[v0];[v0]drawbox=x=0:y={y0}:w=iw:h={bh}:color={cor}@0.92:t=fill{en}[v]"
    sub = str(ass).replace("\\", "/").replace(":", "\\:")
    return v + f";[v]setsar=1,subtitles='{sub}'[vo]"


def game_offset(video, s0, e0, src, cam_box):
    """Pick the x offset of the 1080-wide game crop that avoids static overlays (viewer counters,
    alerts, chat boxes) and the webcam. Static = pixels that barely change across sampled frames
    but carry edges (text/graphics)."""
    try:
        import cv2, numpy as np
    except ImportError:
        return None
    sw, sh = src
    gw = even(sw * GAME_H / sh)
    if gw <= W:
        return 0
    cap = cv2.VideoCapture(str(video)); frames = []
    for k in range(12):
        cap.set(cv2.CAP_PROP_POS_MSEC, (s0 + (e0 - s0) * (k + 0.5) / 12) * 1000)
        ok, f = cap.read()
        if ok:
            frames.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (gw, GAME_H)).astype(np.float32))
    cap.release()
    if len(frames) < 4:
        return None
    st = np.stack(frames)
    std = st.std(0); med = np.median(st, 0)
    edges = cv2.Canny(med.astype(np.uint8), 60, 160) > 0
    bad = (std < 6) & cv2.dilate(edges.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    x, y, w, h = cam_box  # the cam itself also counts as overlay
    bad[int(y * GAME_H):int((y + h) * GAME_H), int(x * gw):int((x + w) * gw)] = True
    col = bad.sum(0).astype(np.float64); cs = np.concatenate([[0], np.cumsum(col)])
    best, bx = None, 0
    camcols = np.zeros(gw); camcols[int(x * gw):int((x + w) * gw)] = 1; cc = np.concatenate([[0], np.cumsum(camcols)])
    for ox in range(0, gw - W + 1, 8):
        # never show the cam twice; otherwise stay near the centre (game subtitles and action sit there),
        # moving off-centre only when that clearly removes a static overlay (counters, alerts, chat)
        if cc[ox + W] - cc[ox] > 0 and (cc[-1] < gw - W):
            continue
        cost = (cs[ox + W] - cs[ox]) * 0.2 + abs(ox - (gw - W) / 2) * GAME_H * 0.05
        if best is None or cost < best:
            best, bx = cost, ox
    return bx


# ------------------------------------------------------------------ edição para retenção (v19)
EDICAO_PADRAO = "pausas,zoom,voz"          # opções: pausas, zoom, voz, loop
PAUSA_MIN = 0.6                            # pausa sem fala acima disso pode sair (se também estiver quieta)
FOLGA = 0.15                               # mantém um respiro em volta das palavras
LOOP_SECS = 0.4


def db_por_decimo(wav, inicio=0, fim=None):
    """Volume (dB) em blocos de 0,1 s; inicio e fim são índices de blocos absolutos."""
    try:
        import wave, numpy as np
        with wave.open(str(wav)) as w:
            total = w.getnframes()
            primeiro = min(total, max(0, int(inicio)) * 1600)
            ultimo = total if fim is None else min(total, max(primeiro, int(fim) * 1600))
            w.setpos(primeiro)
            x = np.frombuffer(w.readframes(ultimo - primeiro), dtype=np.int16).astype(np.float32) / 32768
        n = len(x) // 1600
        return 20 * np.log10(np.sqrt((x[: n * 1600].reshape(n, 1600) ** 2).mean(1) + 1e-9))
    except Exception:
        return None


def trechos_mantidos(words, s0, e0, db=None, pico=None, max_corte=0.35, db_inicio=0):
    """Partes do clipe que ficam (tempos relativos ao começo do clipe). Sai só pausa entre falas que também é
    silenciosa (ação sem fala fica), nunca perto do pico, e no máximo 35% do clipe."""
    dur = e0 - s0
    ws = [w for w in words if s0 <= w["s"] < e0 and w["w"]]
    if len(ws) < 3 or db is None or len(db) == 0:
        return [(0.0, round(dur, 3))]
    ref = None
    if db is not None and len(db):                       # nível da VOZ: mediana do volume enquanto alguém fala
        import numpy as np
        falas = [db[int(w["s"] * 10) - db_inicio:max(int(w["s"] * 10) + 1, int(w["e"] * 10)) - db_inicio] for w in ws]
        falas = np.concatenate([f for f in falas if len(f)]) if any(len(f) for f in falas) else []
        ref = float(np.median(falas)) if len(falas) else None
    cortes = []
    for a, b in zip(ws, ws[1:]):
        g0, g1 = a["e"] + FOLGA, b["s"] - FOLGA
        if b["s"] - a["e"] <= PAUSA_MIN or g1 - g0 < 0.35:
            continue
        if pico is not None and g1 - s0 > pico - 1.5 and g0 - s0 < pico + 1.5:
            continue
        if ref is not None:
            seg = db[int(g0 * 10) - db_inicio:int(g1 * 10) - db_inicio]
            if len(seg) and float(seg.max()) > ref - 6:          # algo alto na pausa (ação, explosão): fica
                continue
        cortes.append((g0 - s0, g1 - s0))
    total = 0.0
    escolhidos = []
    for c in sorted(cortes, key=lambda c: c[0] - c[1]):            # maiores pausas primeiro
        if total + (c[1] - c[0]) > dur * max_corte:
            continue
        escolhidos.append(c); total += c[1] - c[0]
    manter, t = [], 0.0
    for c0, c1 in sorted(escolhidos):
        if c0 > t:
            manter.append((round(t, 3), round(c0, 3)))
        t = c1
    if t < dur:
        manter.append((round(t, 3), round(dur, 3)))
    return manter or [(0.0, round(dur, 3))]


def mapear(t, manter):
    """Tempo do clipe original (relativo) -> tempo no clipe editado."""
    acc = 0.0
    for a, b in manter:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


def duracao_editada(manter):
    return sum(b - a for a, b in manter)


def palavras_editadas(words, s0, e0, manter):
    """Palavras com os tempos do clipe editado (absolutos a partir de s0, como o build_ass espera)."""
    out = []
    for w in words:
        if s0 <= w["s"] < e0 and w["w"]:
            a, b = mapear(w["s"] - s0, manter), mapear(min(w["e"], e0) - s0, manter)
            if b > a:
                out.append(dict(w, s=s0 + a, e=s0 + b))
    return out


def expr_zoom(dur, pico=None, passo=4.0, leve=0.06, forte=0.12):
    """Zoom de leve a cada 'passo' segundos (alterna normal/zoom) e um zoom mais forte no pico da reação."""
    rampa = 0.25
    blocos = []
    t, liga = passo, True
    while t < dur - 1.0:
        fim = min(dur, t + passo)
        if liga:
            blocos.append((t, fim, leve))
        t, liga = fim, not liga
    if pico is not None and 0.5 < pico < dur - 0.5:
        blocos = [b for b in blocos if not (b[0] < pico + 1.2 and b[1] > pico - 0.6)]
        blocos.append((max(0.0, pico - 0.4), min(dur, pico + 1.4), forte))
    if not blocos:
        return None
    termos = [f"{z:.3f}*clip((t-{a:.2f})/{rampa},0,1)*clip(({b:.2f}-t)/{rampa},0,1)" for a, b, z in sorted(blocos)]
    return "1+" + "+".join(termos)


def filtro_edicao(v, manter, zoom=None, dur=None, loop=False):
    """Encaixa no grafo do layout: corte de pausas no começo, zoom antes da legenda e emenda de loop no fim."""
    # Descarte os quadros excedentes antes de aplicar escala, desfoque e zoom.
    entrada = "[0:v]fps=30"
    if manter and len(manter) > 1:
        sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in manter)
        entrada += f",select='{sel}',setpts=N/30/TB"
    usos = v.count("[0:v]")
    rotulos = [f"[vin{i}]" for i in range(usos)]
    if usos > 1:
        entrada += f",split={usos}"
    for rotulo in rotulos:
        v = v.replace("[0:v]", rotulo, 1)
    v = entrada + "".join(rotulos) + ";" + v
    if zoom:
        corpo, fim = v.rsplit(";[v]", 1)
        expr = _re.sub(r"\bt\b", "it", zoom)
        v = (corpo + f";[v]zoompan=z='{expr}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
             f":d=1:s={W}x{H}:fps=30[vz];[vz]" + fim)
    if loop and dur and dur > 3:
        v = v[:-4] + f"[vsub];[vsub]split[lx][ly];[ly]trim=0:{LOOP_SECS},setpts=PTS-STARTPTS[lh];" \
                     f"[lx][lh]xfade=transition=fade:duration=0.3:offset={dur - 0.3:.3f}[vo]"
    return v


def filtro_audio(manter, voz=True, loop=False, dur=None, entrada="[0:a]", saida="[ao]"):
    partes = []
    if manter and len(manter) > 1:
        sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in manter)
        partes += [f"aselect='{sel}'", "asetpts=N/SR/TB"]
    if voz:                                                   # limpeza leve de voz: tira ronco grave e chiado
        partes += ["highpass=f=70", "afftdn=nr=10:nf=-30"]
    partes.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if loop and dur and dur > 3:
        total = dur - 0.3 + LOOP_SECS
        partes += ["afade=t=in:d=0.12", f"afade=t=out:st={dur - 0.35:.3f}:d=0.35", "apad", f"atrim=0:{total:.3f}"]
    return f"{entrada}{','.join(partes)}{saida}"


def tem_audio(src):
    from common import ffprobe
    return any(s.get("codec_type") == "audio" for s in ffprobe(src).get("streams", []))


def comando_render(src, s0, e0, rp, ass, band, saida, voz_mp3=None, hook_secs=2.5):
    """Comando ffmpeg completo (usado pelo cut.py e pelo traduzir.py, para as versões saírem iguais)."""
    manter = [tuple(x) for x in (rp.get("manter") or [])]
    dur = duracao_editada(manter) if manter else (e0 - s0)
    v = video_filter(rp["layout"], rp["cam"], ass, band=band, posicao_jogo=rp.get("posicao_jogo", 50), cam_side=rp.get("side") or "right",
                     src=tuple(rp["src"]) if rp.get("src") else None, game_x=rp.get("gx"),
                     face_expr=tuple(rp["face_expr"]) if rp.get("face_expr") else None)
    v = filtro_edicao(v, manter, rp.get("zoom"), dur, rp.get("loop"))
    cmd = [tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{e0:.2f}", "-i", str(src)]
    threads = str(rp["threads"]) if rp.get("threads") else None
    if threads:
        cmd[1:1] = ["-filter_complex_threads", threads, "-threads:v", threads]
    mapa = ["-map", "[vo]"]
    if tem_audio(src):
        if voz_mp3:
            from common import ffprobe
            dv = float(ffprobe(voz_mp3)["format"]["duration"])
            tempo = f"atempo={min(2.0, dv / hook_secs):.3f}," if dv > hook_secs else ""
            cmd += ["-i", str(voz_mp3)]
            a = (filtro_audio(manter, rp.get("voz", True), rp.get("loop"), dur, saida="[base]") +
                 f";[base]volume=0.2:enable='lt(t,{hook_secs})'[bed];"
                 f"[1:a]{tempo}atrim=0:{hook_secs},afade=t=out:st={hook_secs - 0.15}:d=0.15,apad[tts];"
                 f"[bed][tts]amix=inputs=2:duration=first:normalize=0[ao]")
        else:
            a = filtro_audio(manter, rp.get("voz", True), rp.get("loop"), dur)
        v = v + ";" + a
        mapa += ["-map", "[ao]"]
    from common import codificador_video
    codificador = codificador_video()
    cmd += ["-filter_complex", v, *mapa, *codificador]
    if threads and codificador[1] == "libx264":
        cmd += ["-threads:v", threads]
    cmd += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(saida)]
    return cmd


def titulo_e_faixa(text, style, secs, layout, posicao=None, tamanho=66, cor='rosa'):
    """Gancho e faixa nos primeiros 3 a 8 segundos do clipe."""
    if not text:
        return None, None
    secs = max(3.0, min(8.0, float(secs or 4)))
    tamanho = max(40, min(100, int(tamanho)))
    ty = max(250, min(1450, int(posicao if posicao is not None else (750 if layout == 'facecam' else 1050 if layout == 'react' else 480))))
    n = len(wrap(text, max(12, int(26 * 66 / tamanho))))
    if style == 'box':
        bh = n * int(tamanho * 1.22) + 36
        cores = {'rosa': '0xB92F78', 'laranja': '0xB84C20', 'roxo': '0x4C2875', 'escuro': '0x211830'}
        return ('box', text, ty, secs, tamanho), (ty - bh // 2, bh, secs, cores.get(cor, cores['rosa']))
    return ('outline', text, ty, secs, tamanho), None


def caixa_do_rosto(bx, layout):
    """Câmera sem moldura (só o rosto achado). O find_cam já devolve ~3x a largura do rosto, que é o tamanho
    de uma webcam. No facecam ela é usada como está (antes era alargada 2,6x e o topo mostrava meio jogo);
    se encostar num canto da tela, gruda no canto, como as webcams de live. No react ainda alarga um pouco."""
    x, y, w, h = bx
    if layout == 'react':
        cx, cy = x + w / 2, y + h / 2
        w, h = min(1.0, w * 2.6), min(1.0, h * 2.2)
        x, y = cx - w / 2, cy - h / 2
    else:
        if x < 0.06:
            w, x = w + x, 0.0
        elif x + w > 0.94:
            w = 1.0 - x
        if y < 0.06:
            h, y = h + y, 0.0
        elif y + h > 0.94:
            h = 1.0 - y
    w, h = min(1.0, w), min(1.0, h)
    return [min(max(0.0, x), 1 - w), min(max(0.0, y), 1 - h), w, h]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--layout", choices=["fill", "blur", "facecam", "react"], default="facecam")
    ap.add_argument("--title", default="", help="reaction title, e.g. 'Speed REALIZED why GTA 6 took 13 YEARS'")
    ap.add_argument("--title-style", choices=["box", "outline"], default="box")
    ap.add_argument("--title-secs", type=float, default=4, help="duração da faixa em segundos (3 a 8; padrão: 4)")
    ap.add_argument("--texto-y", type=int, default=None)
    ap.add_argument("--texto-tamanho", type=int, default=66)
    ap.add_argument("--texto-cor", choices=['rosa', 'laranja', 'roxo', 'escuro'], default='rosa')
    ap.add_argument("--captions", choices=["word", "bubble", "none"], default="word")
    ap.add_argument("--hook", default="")
    ap.add_argument("--allow-profanity", action="store_true", help="keep swear words in captions (slurs are always masked)")
    ap.add_argument("--cam", default="auto", help="auto (find the webcam) or x:y:w:h fractions")
    ap.add_argument("--posicao-jogo", type=int, choices=range(101), default=50)
    ap.add_argument("--game-x", type=int, default=None, help="enquadramento horizontal já calculado")
    ap.add_argument("--start", type=float); ap.add_argument("--end", type=float)
    ap.add_argument("--edicao", default=EDICAO_PADRAO, help="pausas,zoom,voz,loop (ou 'nenhuma')")
    ap.add_argument("--pergunta", default=None, help="pergunta aberta para o post (padrão: a sugerida pela IA)")
    ap.add_argument("--threads", type=int, choices=range(1, 9), help="limite de processamento para cortes em paralelo")
    ap.add_argument("--amostra", action="store_true")
    a = ap.parse_args()
    inicio_corte = perf_counter()
    d = Path(a.job); c = load_json(d / "candidates.json")
    print("(1/2) preparando legenda e enquadramento…", flush=True)
    pick = next(x for x in c["candidates"] if x["n"] == a.pick)
    s0 = a.start if a.start is not None else pick["start"]; e0 = a.end if a.end is not None else pick["end"]
    words = load_json(d / "transcript.json")
    out = d / "edits"; out.mkdir(exist_ok=True)
    if a.amostra:
        out = out / "amostras"
        out.mkdir(exist_ok=True)
    layout, cam, side = a.layout, a.cam, 'right'
    face_expr = None
    if layout in ('react', 'facecam') and cam == 'auto':
        from facecam import find_cam
        r = find_cam(c['source'], s0, e0)
        if layout == 'react' and r.get('mode') not in ('cam', 'face'):
            sys.exit(f"pulado: neste trecho não há o rosto do streamer sobre o jogo ({r.get('mode')}: {r.get('reason', '')}). "
                     "O clipe de reação precisa do jogo na tela e da câmera num quadro à parte. Escolha outro momento "
                     "ou use o layout Desfocado.")
        if layout == 'react':
            from facecam import has_gameplay, face_crop_expr
            if not has_gameplay(c['source'], s0, e0, r['box']):
                sys.exit("pulado: fora da câmera não há jogo na tela neste trecho. Escolha um momento com o GTA 6 na tela.")
            if r.get('mode') == 'face' and r.get('face_track'):
                from common import ffprobe as _fp
                _vs = [x for x in _fp(c['source'])['streams'] if x.get('codec_type') == 'video'][0]
                from facecam import inner_edges
                sw_, sh_ = int(_vs['width']), int(_vs['height'])
                bnd = inner_edges(c['source'], s0, e0, r['face'], sw_, sh_)
                print(f'facecam: cam borders L{bnd[0]} T{bnd[1]} R{bnd[2]} B{bnd[3]} px')
                fe = face_crop_expr(r['face_track'], sw_, sh_, W, TOP, bounds=bnd)
                face_expr = (fe['w'], fe['h'], fe['x'], fe['y'])
                print(f"facecam: no clean cam frame, tracking the face ({r.get('summary', '')})")
        if r.get('mode') in ('cam', 'face'):
            bx = list(r['box'])
            if r['mode'] == 'face':
                bx = caixa_do_rosto(bx, layout)
            cam = ':'.join(f'{v:.4f}' for v in bx)
            side = 'left' if r['box'][0] + r['box'][2] / 2 < 0.5 else 'right'
            print(f"facecam: {r.get('mode')} box {cam} ({r.get('summary', '')})")
        else:
            sys.exit("Câmera não identificada neste trecho. Selecione outro momento ou formato.")

    elif layout in ('react', 'facecam') and cam != 'auto':
        side = 'left' if float(cam.split(':')[0]) + float(cam.split(':')[2]) / 2 < 0.5 else 'right'
    cap_y = CAP_Y[layout]
    texto = a.title or a.hook or (pick.get("gancho_sugerido") or " ".join((pick.get("text") or "").split()[:9]) or c.get("info", {}).get("title", ""))[:90]
    title_secs = max(3.0, min(8.0, float(a.title_secs or 4)))
    title, band = titulo_e_faixa(texto, a.title_style, title_secs, layout,
                                 a.texto_y, a.texto_tamanho, a.texto_cor)
    ed = {x.strip() for x in (a.edicao or "").split(",")} - {"", "nenhuma"}
    pico_abs = pick.get("peak")
    manter = [(0.0, round(e0 - s0, 3))]
    if "pausas" in ed:
        inicio_db = max(0, int(s0 * 10))
        # Uma palavra iniciada no corte pode terminar depois de e0; inclua-a na referência da voz.
        fim_db = max([e0] + [w["e"] for w in words if s0 <= w["s"] < e0 and w["w"]])
        db = db_por_decimo(d / "audio.wav", inicio_db, int(fim_db * 10) + 1)
        manter = trechos_mantidos(words, s0, e0, db,
                                  (pico_abs - s0) if pico_abs is not None else None, db_inicio=inicio_db)
    dur = duracao_editada(manter)
    pico_ed = mapear(pico_abs - s0, manter) if pico_abs is not None and s0 <= pico_abs <= e0 else None
    zoom = expr_zoom(dur, pico_ed) if "zoom" in ed and layout in ("blur", "fill") else None
    tirado = (e0 - s0) - dur
    if tirado > 0.05:
        print(f"   pausas: {len(manter) - 1} corte(s), {tirado:.1f} s a menos ({e0 - s0:.0f} s -> {dur:.0f} s)", flush=True)
    ass = out / f"clip_{a.pick}.ass"
    caps = a.captions
    cap_words = palavras_editadas(words, s0, e0, manter) if caps != 'none' else []
    ass.write_text(build_ass(cap_words, s0, s0 + dur, '', cap_y, title=title, caps=caps, profanity=a.allow_profanity), encoding="utf-8")
    src = None; gx = None
    if layout == 'react':
        from common import ffprobe
        vs = [x for x in ffprobe(c['source'])['streams'] if x.get('codec_type') == 'video'][0]
        src = (int(vs['width']), int(vs['height']))
        if a.game_x is None:
            gx = game_offset(c['source'], s0, e0, src, [float(t) for t in cam.split(':')])
        else:
            largura_jogo = max(W, even(src[0] * GAME_H / src[1]))
            gx = max(0, min(largura_jogo - W, even(a.game_x)))
    rp = {"posicao_jogo": a.posicao_jogo, "layout": layout, "cam": cam, "side": side, "src": src, "gx": gx, "face_expr": face_expr,
          "manter": manter if len(manter) > 1 else None, "zoom": zoom, "voz": "voz" in ed, "loop": "loop" in ed,
          "threads": a.threads}
    mp4 = out / f"clip_{a.pick}.mp4"
    parcial = out / f"clip_{a.pick}.parcial.mp4"
    meta_anterior = load_json(out / f"clip_{a.pick}.json") if (out / f"clip_{a.pick}.json").exists() else {}
    print(f"(2/2) renderizando {dur:.0f}s em 1080x1920 ({layout}{', ' + ', '.join(sorted(ed)) if ed else ''})…", flush=True)
    inicio_render = perf_counter()
    comando = comando_render(c["source"], s0, e0, rp, ass, band, parcial)
    if a.amostra:
        comando[-1:-1] = ["-t", str(min(dur, 5))]
        executar_render(comando, min(dur, 5))
        parcial.replace(mp4)
        print(f"ok: {mp4}")
        return
    executar_render(comando, dur)
    fim_render = perf_counter()
    if mp4.exists():
        import shutil, time
        pasta_backup = out / "backup"; pasta_backup.mkdir(exist_ok=True)
        shutil.copy2(mp4, pasta_backup / f"clip_{a.pick}_{time.time_ns()}.mp4")
    parcial.replace(mp4)
    info = c.get("info", {})
    save_json(out / f"clip_{a.pick}.json", {"tempos": {"preparo": round(inicio_render-inicio_corte, 3), "render": round(fim_render-inicio_render, 3)},
                                            "file": str(mp4), "start": s0, "end": e0, "layout": layout,
                                            "hook": a.hook or (title[1] if title and layout != 'react' else ""),
                                            "title": a.title or (title[1] if title and layout == 'react' else ""), "cam": cam,
                                            "duracao": round(dur, 2), "pico": round(pico_ed, 2) if pico_ed is not None else None,
                                            "pergunta": (a.pergunta if a.pergunta is not None else (pick.get("pergunta") or meta_anterior.get("pergunta") or "")).strip()[:160],
                                            "nota_momento": pick.get("nota"), "tipo": (pick.get("ia") or {}).get("tipo"),
                                            "primeira_fala": round(cap_words[0]["s"] - s0, 2) if cap_words else None,
                                            "projetos": meta_anterior.get("projetos") or {},
                                            "source_url": info.get("webpage_url"), "source_title": info.get("title"),
                                            "source_channel": info.get("channel") or info.get("uploader"),
                                            "render": {"posicao_jogo": a.posicao_jogo, "layout": layout, "cam": cam, "side": side, "src": src, "gx": gx,
                                                       "face_expr": face_expr, "title_style": a.title_style,
                                                       "title_secs": title_secs, "captions": caps,
                                                       "texto_y": a.texto_y, "texto_tamanho": a.texto_tamanho, "texto_cor": a.texto_cor,
                                                       "profanity": a.allow_profanity, "cap_y": cap_y,
                                                       "texto_y_final": title[2] if title else None,
                                                       "manter": rp["manter"], "zoom": zoom, "voz": rp["voz"], "loop": rp["loop"],
                                                       "edicao": sorted(ed)}})
    print(f"ok: {mp4}")


if __name__ == "__main__":
    main()
