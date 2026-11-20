"""Gera um script ExtendScript (.jsx) que recria a montagem no After Effects para finalização manual.

  python exportar_ae.py out/timeline.json [--saida out/projeto_ae.jsx]

No After Effects: File > Scripts > Run Script File... > projeto_ae.jsx
Cria a comp "GTA6_SHORT" 1080x1920 com: clipes cortados nos tempos certos (cheio ou moldura com fundo
desfocado), narração, música e uma camada de texto por palavra (fonte Bangers, contorno preto, "pop").
Os caminhos dos clipes são os do computador onde montar.py rodou — rode montar/exportar no mesmo PC do AE.
Instale assets/fonts/Bangers-Regular.ttf no Windows antes (clique direito > Instalar).
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from comum import ler_json, normalizar


def ass_para_rgb(c):
    h = c.replace("&H", "").replace("&", "")[-6:]
    b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return [round(r / 255, 3), round(g / 255, 3), round(b / 255, 3)]


JSX = r"""// gerado por gta6-shorts/exportar_ae.py
(function () {
var T = __DADOS__;
app.beginUndoGroup("GTA6 short");
var proj = app.project || app.newProject();
var pasta = proj.items.addFolder("GTA6_clipes");
var cache = {};
function importar(p) {
  if (cache[p]) return cache[p];
  var f = new File(p);
  if (!f.exists) { alert("Arquivo não encontrado: " + p); return null; }
  var it = proj.importFile(new ImportOptions(f)); it.parentFolder = pasta; cache[p] = it; return it;
}
var comp = proj.items.addComp("GTA6_SHORT", T.largura, T.altura, 1, T.total, T.fps);
function cobrir(layer, item, larg, alt, foco, c) {
  var s = Math.max(larg / item.width, alt / item.height) * 100;
  layer.property("Scale").setValue([s, s]);
  var sobra = item.width * s / 100 - larg;
  if (foco instanceof Array) {                       // panorâmica: desliza de foco[0] até foco[1]
    layer.property("Position").setValueAtTime(c.t0, [T.largura / 2 + sobra * (0.5 - foco[0]), T.altura / 2]);
    layer.property("Position").setValueAtTime(c.t0 + c.dur, [T.largura / 2 + sobra * (0.5 - foco[1]), T.altura / 2]);
  } else {
    layer.property("Position").setValue([T.largura / 2 + sobra * (0.5 - foco), T.altura / 2]);
  }
}
for (var i = 0; i < T.cortes.length; i++) {
  var c = T.cortes[i], it = importar(c.arquivo);
  if (!it) continue;
  var camadas = [];
  var vertical = it.height * T.largura / it.width > T.altura * 0.8;
  if (c.layout == "inteiro" && !vertical) {        // quadro inteiro na largura + fundo desfocado
    var bgi = comp.layers.add(it); cobrir(bgi, it, T.largura, T.altura, 0.5, c);
    bgi.property("Effects").addProperty("ADBE Gaussian Blur 2").property(1).setValue(70);
    bgi.property("Effects").addProperty("ADBE Brightness & Contrast 2").property(1).setValue(-25);
    bgi.name = "fundo " + c.cena; camadas.push(bgi);
    var fgi = comp.layers.add(it), si = T.largura / it.width * 100;
    fgi.property("Scale").setValue([si, si]);
    fgi.property("Position").setValue([T.largura / 2, T.altura / 2]);
    fgi.name = c.cena; camadas.push(fgi);
  } else if (c.layout == "moldura") {
    var bg = comp.layers.add(it); cobrir(bg, it, T.largura, T.altura, 0.5, c);
    var blur = bg.property("Effects").addProperty("ADBE Gaussian Blur 2");
    blur.property(1).setValue(60);
    bg.property("Effects").addProperty("ADBE Brightness & Contrast 2").property(1).setValue(-20);
    bg.name = "fundo " + c.cena; camadas.push(bg);
    var fg = comp.layers.add(it);
    var mh = T.estilo.moldura_altura;
    var s = Math.max(T.largura / it.width, mh / it.height) * 100;
    fg.property("Scale").setValue([s, s]);
    var m = fg.Masks.addProperty("Mask"), sh = new Shape();
    var w = it.width, h = it.height, vw = T.largura * 100 / s, vh = mh * 100 / s;
    var fm = (c.foco instanceof Array) ? c.foco[0] : c.foco;
    var x0 = (w - vw) * fm, y0 = (h - vh) / 2;
    sh.vertices = [[x0, y0], [x0 + vw, y0], [x0 + vw, y0 + vh], [x0, y0 + vh]]; sh.closed = true;
    m.property("Mask Path").setValue(sh);
    fg.property("Position").setValue([T.largura / 2 + (w / 2 - (x0 + vw / 2)) * s / 100, T.altura / 2]);
    fg.name = c.cena; camadas.push(fg);
  } else {
    var l = comp.layers.add(it); cobrir(l, it, T.largura, T.altura, c.foco, c); l.name = c.cena; camadas.push(l);
  }
  for (var k = 0; k < camadas.length; k++) {
    var L = camadas[k];
    if (L.hasAudio) L.audioEnabled = false;
    L.startTime = c.t0 - c.src_in; L.inPoint = c.t0; L.outPoint = c.t0 + c.dur;
    if (c.zoom > 0 && (L.name.indexOf("fundo ") != 0)) {                       // push-in / pull-out alternado, igual ao montar.py
      var s0 = L.property("Scale").value, s1 = [s0[0] * (1 + c.zoom), s0[1] * (1 + c.zoom)];
      var a = (i % 2 == 0) ? s0 : s1, b = (i % 2 == 0) ? s1 : s0;
      L.property("Scale").setValueAtTime(c.t0, a); L.property("Scale").setValueAtTime(c.t0 + c.dur, b);
    }
  }
  for (var g = 0; g < c.imagem.length; g++) {
    var ig = c.imagem[g], im = importar(ig.arquivo);
    if (!im) continue;
    var li = comp.layers.add(im); li.inPoint = c.t0; li.outPoint = c.t0 + c.dur;
    var esc = T.largura * (ig.escala || 0.6) / im.width * 100;
    li.property("Scale").setValue([esc, esc]);
    var yy = (typeof ig.y == "number") ? ig.y : 220;
    li.property("Position").setValue([T.largura / 2, yy + im.height * esc / 200]);
  }
}
var nar = importar(T.narracao); if (nar) comp.layers.add(nar).name = "NARRACAO";
if (T.musica) { var mu = importar(T.musica); if (mu) { var lm = comp.layers.add(mu); lm.name = "MUSICA";
  lm.property("Audio Levels").setValue([-17, -17]); } }
if (T.sfx) { var sx = importar(T.sfx); if (sx) comp.layers.add(sx).name = "EFEITOS"; }
var E = T.estilo;
for (var q = 0; q < T.cartelas.length; q++) {
  var ca = T.cartelas[q], cl = comp.layers.addText(ca.texto);
  var cd = cl.property("Source Text").value;
  cd.resetCharStyle(); cd.font = "Bangers-Regular"; cd.fontSize = E.cartela_tamanho;
  cd.fillColor = T.cor_destaque; cd.applyStroke = true; cd.strokeColor = [0, 0, 0];
  cd.strokeWidth = (E.contorno + 2) * 2; cd.strokeOverFill = false;
  cd.justification = ParagraphJustification.CENTER_JUSTIFY;
  cl.property("Source Text").setValue(cd);
  cl.property("Position").setValue([T.largura / 2, ca.y + E.cartela_tamanho * 0.35]);
  cl.property("Rotation").setValue(-4);
  cl.inPoint = ca.inicio; cl.outPoint = ca.fim; cl.name = "cartela " + ca.texto;
  var cs = cl.property("Scale");
  cs.setValueAtTime(ca.inicio, [60, 60]); cs.setValueAtTime(ca.inicio + 0.12, [108, 108]);
  cs.setValueAtTime(ca.inicio + 0.2, [100, 100]);
}
for (var j = 0; j < T.palavras.length; j++) {
  var p = T.palavras[j];
  var tl = comp.layers.addText(p.texto);
  var td = tl.property("Source Text").value;
  td.resetCharStyle(); td.font = "Bangers-Regular"; td.fontSize = E.tamanho;
  td.fillColor = p.destaque ? T.cor_destaque : T.cor; td.applyStroke = true;
  td.strokeColor = [0, 0, 0]; td.strokeWidth = E.contorno * 2; td.strokeOverFill = false;
  td.justification = ParagraphJustification.CENTER_JUSTIFY;
  tl.property("Source Text").setValue(td);
  tl.property("Position").setValue([T.largura / 2, E.legenda_y + E.tamanho * 0.35]);
  tl.inPoint = p.inicio; tl.outPoint = p.fim;
  var sc = tl.property("Scale");
  sc.setValueAtTime(p.inicio, [72, 72]); sc.setValueAtTime(p.inicio + 0.08, [114, 114]);
  sc.setValueAtTime(p.inicio + 0.15, [100, 100]);
  tl.name = "txt " + p.texto;
}
comp.openInViewer();
app.endUndoGroup();
})();
"""


def imagens(img):
    """normaliza imagem/lista de imagens do corte para caminhos absolutos (assets da skill pelo nome)."""
    from montar import caminho_asset
    if not img:
        return []
    lst = [img] if isinstance(img, dict) else img
    return [{**i, "arquivo": caminho_asset(i["arquivo"]).as_posix()} for i in lst]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("--saida")
    a = ap.parse_args()
    t = ler_json(a.timeline)
    est = t["estilo"]
    rot_dest = {}
    palavras = []
    for k, p in enumerate(t["palavras"]):
        prox = t["palavras"][k + 1]["inicio"] if k + 1 < len(t["palavras"]) else t["total"]
        fim = min(prox, p["fim"] + 0.6) if prox - p["fim"] > 0.6 else prox
        txt = p["palavra"].strip(" ,;")
        palavras.append({"texto": txt.upper() if est["maiusculas"] else txt, "inicio": p["inicio"],
                         "fim": max(fim, p["inicio"] + 0.08), "destaque": p.get("destaque", False)})
    dados = {"largura": t["largura"], "altura": t["altura"], "fps": t["fps"], "total": t["total"],
             "estilo": est, "cor": ass_para_rgb(est["cor"]), "cor_destaque": ass_para_rgb(est["cor_destaque"]),
             "narracao": Path(t["narracao"]).as_posix(),
             "musica": Path(t["musica"]).as_posix() if t.get("musica") else None,
             "cortes": [{**c, "arquivo": Path(c["arquivo"]).as_posix(),
                         "imagem": imagens(c.get("imagem"))} for c in t["cortes"]],
             "palavras": palavras, "cartelas": t.get("cartelas", []),
             "sfx": Path(t["sfx"]).as_posix() if t.get("sfx") and Path(t["sfx"]).exists() else None}
    saida = Path(a.saida or Path(a.timeline).with_name("projeto_ae.jsx"))
    saida.write_text(JSX.replace("__DADOS__", json.dumps(dados, ensure_ascii=False)), encoding="utf-8-sig")
    print(f"ok: {saida}  (After Effects > File > Scripts > Run Script File)")


if __name__ == "__main__":
    main()
