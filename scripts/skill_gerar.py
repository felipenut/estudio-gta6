"""Gera a skill do Claude para ESTE PC (pasta skill/ dentro da pasta de dados).

  python skill_gerar.py            -> skill/gta6-shorts/SKILL.md (+ references) e skill/gta6-shorts.zip

O SKILL.md leva o caminho real da pasta de dados, para o Claude achar tudo em qualquer PC.
O .zip pode ser enviado em claude.ai (Configurações > Capacidades > Skills > Enviar skill).
"""
import json, shutil, sys, zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FERR = AQUI.parent
RAIZ = FERR.parent
NOME = "gta6-shorts"
REFS = ["roteiro.md", "roteiro_exemplo.json", "estilo.md", "biblioteca.md", "temas.md", "series.json"]

MODELO = r"""---
name: gta6-shorts
description: Estúdio GTA 6 Shorts deste PC. Use para escrever roteiros dos pedidos do Estúdio, etiquetar cenas da biblioteca, sugerir temas, ler os resultados dos posts e ajustar o programa. Use sempre que o usuário falar em Estúdio, pedido, roteiro, lote, biblioteca de cenas, temas, Zernio ou vídeos de GTA 6.
---

# Estúdio GTA 6 Shorts ({PC})

Programa no Windows que faz vídeos verticais de 60–70 s sobre GTA 6 (roteiro → narração → cortes → legenda → capa → agendamento).
**O Claude escreve os roteiros e etiqueta as cenas**; o programa faz o resto (Gerar vídeo, Gerar lote, Agendar no Zernio).

## Onde fica tudo
Pasta de dados: `{RAIZ}`
- `ferramentas/scripts/` — código do Estúdio (estudio.py, estudio.html, montar.py, narrar.py, zernio.py, variacao.py…)
- `ferramentas/references/` — **leia antes de escrever**: `roteiro.md` (fórmula e campos), `roteiro_exemplo.json`, `estilo.md`, `biblioteca.md`, `temas.md`, `series.json`
- `biblioteca/biblioteca.json` — cenas (id `VIDEO#N`, descricao, tags), `biblioteca/miniaturas/` — folhas para etiquetar
- `videos/AAAA-MM-DD_tema/` — um projeto por vídeo: `pedido.json`, `roteiro.json`, `post.txt`, `status.txt`, `out/`
- `videos/_tendencias.json` — vídeos de GTA 6 em alta no YouTube; `videos/_resultados.json` — views/curtidas dos posts
- `musicas/` — trilhas; `ferramentas/variacao.json` — regra de voz/música
- **Nunca leia, copie nem peça** `ferramentas/config.json` e `ferramentas/zernio.json` (chaves do usuário).

## Como acessar o PC
Peça para o usuário conectar a pasta `{RAIZ}` (no app desktop do Claude: + > Add folder), se ainda não estiver.
Use as ferramentas de pasta do dispositivo: listar, trazer arquivos (stage) e gravar (commit).
Ao gravar: escreva sempre num caminho novo de saída, grave com força e confira o md5 trazendo o arquivo de volta.
Sem terminal no PC: quem roda as coisas é o usuário, pelos botões do Estúdio.

## Pedido → roteiro (o trabalho principal)
1. Ache os pedidos: pastas em `videos/` com `pedido.json` e sem `roteiro.json` (status "AGUARDANDO ROTEIRO").
2. Pesquise o tema na web (datas, números, falas oficiais, rumores marcados como rumor). Nunca invente número.
3. Escreva `roteiro.json` seguindo `references/roteiro.md` e o exemplo: 150–185 palavras, gancho ≤ 16 palavras com "GTA 6"
   e fato forte, blocos fato → reação/piada → micro-gancho, CTA leve no meio, payoff, CTA final com pergunta.
   Campos úteis: `titulo`, `capa`, `serie` (mesma série = mesma voz/música), `fontes`, e em cada segmento
   `tipo`, `texto`, `destaque` (1–2 itens, cada um UMA palavra que está no texto), `cartela`, `imagem`, `sfx`, `clipes` [{"cena": "VIDEO#N", "foco": 0.5}].
   Antes de gravar, confira as regras do checar_roteiro.py (150–185 palavras, gancho ≤ 16 com "GTA 6", 2+ micro-ganchos, CTA final com "?").
4. Cenas: escolha em `biblioteca/biblioteca.json` pelas tags/descrição, 2–3 por segmento, sem repetir no vídeo.
   **Evite cenas usadas nos últimos 10 roteiros** (leia os `roteiro.json` recentes). Nunca use cenas com tag `ruim`.
5. Varie gancho e CTA em relação aos últimos vídeos. Olhe `videos/_resultados.json`: repita o que teve mais views.
6. Escreva `post.txt` (legenda curta com pergunta + 5–8 hashtags) e `status.txt` = `ROTEIRO PRONTO (Claude)`.
7. Avise o usuário: no Estúdio, abrir o projeto → Prévia/Gerar vídeo (ou ▶ Gerar lote para vários).

## Etiquetar a biblioteca
Cenas sem tags aparecem em Biblioteca de cenas. Abra as folhas `biblioteca/miniaturas/<video>_folha_N.jpg`, descreva
cada cena (quem, onde, ação) e grave as tags no `biblioteca.json` (formato em `references/biblioteca.md`).
Cenas com texto de trailer, logo, tela preta ou marca d'água: tag `ruim`.

## Temas
`references/temas.md` (catálogo; temas usados saem sozinhos), `references/series.json` (fórmulas infinitas),
`videos/_tendencias.json` (botão Tendências do Estúdio). Para reabastecer: pesquise e acrescente temas no `temas.md`.

## Regras de qualidade
- Gancho com imagem forte e tema dito no 1º segundo; troca de imagem a cada 2–3 s; imagem ilustra a fala.
- Fatos atuais sempre pesquisados na hora; rumor = "segundo rumores". Escreva "GTA 6" (VI só em cartela).
- Humor leve estilo TV aberta; nada sexual explícito, menores, assédio ou preconceito.
- Material oficial da Rockstar de preferência; nada de vídeos de outros criadores com marca d'água/facecam.
"""


def gerar():
    destino = RAIZ / "skill" / NOME
    (destino / "references").mkdir(parents=True, exist_ok=True)
    import platform
    txt = MODELO.replace("{RAIZ}", str(RAIZ)).replace("{PC}", platform.node() or "este PC")
    (destino / "SKILL.md").write_text(txt, encoding="utf-8")
    for r in REFS:
        src = FERR / "references" / r
        if src.is_file():
            shutil.copy2(src, destino / "references" / r)
    z = RAIZ / "skill" / f"{NOME}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        for arq in sorted(destino.rglob("*")):
            if arq.is_file():
                f.write(arq, arq.relative_to(destino.parent).as_posix())
    return {"skill": str(destino / "SKILL.md"), "zip": str(z), "raiz": str(RAIZ), "prompt": prompt()}


def prompt():
    s = RAIZ / "skill" / NOME / "SKILL.md"
    return (f"Este é o meu Estúdio GTA 6 Shorts. A pasta de dados é {RAIZ} (conectei esta pasta aqui). "
            f"Leia a skill em {s} e siga essa skill daqui em diante: você escreve os roteiros dos pedidos, "
            f"etiqueta as cenas da biblioteca e cuida dos temas. Depois de ler, me proponha salvá-la como skill "
            f"e diga quantos pedidos estão aguardando roteiro.")


if __name__ == "__main__":
    print(json.dumps(gerar(), ensure_ascii=False, indent=1))
