# Como escrever o roteiro (fórmula dos vídeos de referência)

Os vídeos de referência têm 65 a 70 s e uma narração rápida e contínua, sem silêncio. Cada frase entrega
um fato, uma reação ou um gancho. O objetivo é que ninguém consiga sair antes do fim.

## Tamanho e ritmo
- **150 a 185 palavras**, o que dá 60 a 70 s com a voz `pt-BR-AntonioNeural` a `+12%`.
- Escreva frases curtas (6 a 14 palavras), em linguagem falada brasileira ("cê", "tá", "pra", "mano" com moderação).
- Cada segmento do JSON tem 1 ou 2 frases e uma única ideia visual. Normalmente são 8 a 14 segmentos.

## Estrutura
| Tempo | Bloco | O que fazer |
|---|---|---|
| 0–3 s | **GANCHO** | Afirmação chocante, pergunta impossível ou "a Rockstar escondeu...". Nada de "olá" nem "hoje vamos falar". O tema aparece no 1º segundo. |
| 3–10 s | **PROMESSA / LOOP ABERTO** | Contexto rápido e uma promessa: "e o último detalhe é o mais insano". |
| 10–45 s | **CORPO** | 3 ou 4 blocos de curiosidade ou história, de 8 a 12 s cada. Cada bloco segue a sequência fato → reação ou piada → micro-gancho ("mas isso não é nada perto de..."). |
| ~50% | **CTA LEVE** | Uma frase só, sem quebrar o ritmo: "salva esse vídeo pra mostrar pro teu amigo que duvida". |
| 45–60 s | **PAYOFF** | Entregue a promessa do início com o fato mais forte. |
| final | **CTA FINAL + LOOP** | Pergunta que gere comentários (polêmica leve, escolha A ou B) + "segue pra parte 2". Se der, termine numa frase que encaixe no começo do vídeo, para ele rodar em loop. |

## Ingredientes (misture pelo menos 4 por vídeo)
- **Curiosidades**: números concretos (tamanho do mapa, quantidade de NPCs, anos de desenvolvimento, orçamento). Antes de escrever, pesquise com WebSearch. Se for rumor ou vazamento, diga "segundo rumores".
- **Histórias**: bastidores da Rockstar, inspirações na Flórida real (Florida Man, notícias bizarras), casos de jogadores, comparações com GTA V, GTA Vice City (2002) e RDR2.
- **Comparações**: GTA 6 x GTA V, com o mesmo tipo de cena lado a lado. Use o layout `moldura` ou dois cortes seguidos.
- **Piadas**: exagero e autodepreciação ("meu PC já pediu demissão só de ler isso"), referência a meme brasileiro, reação de NPC.
- **Duplo sentido leve**: insinuação inocente, estilo humor de TV aberta, que se desfaz na hora ("dá pra encher o tanque... do carro, gente, do CARRO"; "Vice City é quente, e não tô falando do clima"; "o Jason pega pesado... na academia"). No máximo 1 ou 2 por vídeo. **Nunca** usar conteúdo sexual explícito, piada com menor, assédio ou piada contra raça, religião, gênero ou orientação.
- **Perguntas diretas** ao espectador ("você faria isso?") para manter a conversa.
- **Quebra de padrão** a cada 10 a 15 s: mudança de tom, efeito sonoro, contagem ("3 coisas..."), frase de uma palavra só ("Detalhe:").

## Ganchos que funcionam (adapte ao tema)
- "O GTA 6 vai ser tão realista que [consequência absurda]."
- "A Rockstar fez uma coisa no GTA 6 que nenhum jogo teve coragem de fazer."
- "Se você jogar o GTA 6 [no dia X / desse jeito], [algo inesperado] vai acontecer."
- "Isso aqui não é a vida real. É o GTA 6."
- "Pararam de rir quando viram [detalhe] do GTA 6."
- "Tem um detalhe no trailer do GTA 6 que 99% das pessoas não viu."

## CTAs (varie e nunca repita o mesmo do vídeo anterior)
- Comentário: "comenta 'Lucia' ou 'Jason': quem você vai jogar primeiro?"
- Salvar ou compartilhar: "manda pro amigo que diz que o GTA 6 vai flopar".
- Seguir: "segue que amanhã eu mostro [próximo tema]", que já anuncia a série.

## Formato do roteiro.json
Modelo completo e aprovado pelo checador: `roteiro_exemplo.json`. Os caminhos são relativos à pasta raiz
`skill-gta6`, que é de onde os scripts rodam.
```jsonc
{
  "titulo": "GTA 6 vai ter clima dinâmico insano",
  "tema": "clima e furacões no GTA 6",
  "capa": "O GTA 6 VAI TER FURACÃO",          // texto da capa.jpg (padrão: titulo)
  "fontes": ["url ou site + o que confirmou"],   // registro das fontes pesquisadas
  "voz": "pt-BR-AntonioNeural", "velocidade": "+12%", "tom": "+0Hz",
  "musica": "musicas/tensa_01.mp3",              // opcional: sem isso, sorteia uma da pasta musicas/
  "estilo": {"ritmo_corte": 2.4, "barra_progresso": false, "zoom": 0.06, "sfx": true},
  "segmentos": [
    {"tipo": "gancho", "texto": "O GTA 6 vai ter furacão de verdade.",
     "busca": "tempestade chuva vento", "tags": ["clima", "chuva"],
     "destaque": ["furacão"], "layout": "cheio", "sfx": "impacto",
     "cartela": "CATEGORIA 5",
     "imagem": [{"arquivo": "seta_baixo.png", "escala": 0.25, "y": 300}]},
    {"tipo": "curiosidade", "texto": "...",
     "clipes": [{"cena": "GTA6_Trailer_1#14"}, {"cena": "GTA6_Trailer_2#3", "foco": 0.3, "zoom": 0}]}
  ]
}
```
| Campo | O que faz |
|---|---|
| `tipo` | Um destes: gancho, promessa, historia, curiosidade, piada, duplo_sentido, comparacao, pergunta, cta, payoff. O checador usa para avaliar a variedade. |
| `texto` | O que a voz fala. Escreva "GTA 6" e "GTA 5" (a voz lê "VI" errado) e os números como devem aparecer na legenda. |
| `clipes` | Escolha manual de cenas (id da biblioteca ou `{"arquivo", "inicio"}`). Sem ele, o `montar.py` escolhe sozinho por `busca` + `tags`. **Prefira escolher à mão**, olhando as miniaturas. |
| `foco` | Posição da janela 9:16 dentro da cena: 0 = esquerda, 0,5 = centro, 1 = direita. Uma lista `[0.1, 0.8]` faz **panorâmica** (a janela desliza durante o corte): use quando duas pessoas não cabem juntas. |
| `layout` | `auto` (**padrão**: tela cheia com o recorte no assunto; vira `inteiro` sozinho em logo/texto/capa/mapa), `cheio` (tela cheia, com `foco`), `inteiro` (quadro 16:9 todo com fundo desfocado: só quando cortar estraga a cena) ou `moldura`. Faixas pretas de cinema são removidas sozinhas. |
| `destaque` | 1 ou 2 palavras do texto que aparecem em amarelo e tocam um "pop". |
| `cartela` | Texto grande e amarelo, inclinado, durante o segmento todo (data, número, "MITO"). Use `"\n"` para quebrar linha, ou `{"texto", "y", "inclinacao"}`. |
| `imagem` | PNG (ou lista) sobreposto durante o segmento. Assets prontos: `seta_cima/baixo/esquerda/direita/diagonal.png`, `circulo.png`, `x_vermelho.png`, `check_verde.png`. `y` é o topo da imagem em px (0 a 1920) e `escala` é a fração da largura. |
| `sfx` | Som extra no começo do segmento: `impacto`, `whoosh`, `whoosh_cine`, `pop`, `glitch`, `riser`, `notificacao`, `dinheiro`, `relogio`. Os automáticos já existem: impacto no início, som nas transições fortes, sons dos efeitos de interface e pop nos destaques. |
| `efeitos` | Lista de elementos de interface no estilo do HUD do GTA 6 (veja "Efeitos de interface" abaixo). |
| `transicao` | Como o segmento entra: `corte` (seco), `zoom`, `whip` (chicote), `glitch` ou `flash`. Sem o campo, o vídeo usa corte seco e põe uma transição forte sozinho a cada 3 trocas de assunto (`estilo.transicao_a_cada`; `estilo.transicoes: "nenhuma"` desliga). |
| `revelacao` | `true` na virada principal do vídeo: um riser sobe até o corte e a cena entra com glitch. Use uma vez por vídeo. |
| `tremer` | `true` faz a câmera tremer no segmento todo (briga, batida, explosão, fuga). |
| `zoom` | Intensidade do zoom suave por corte (padrão 0,06; 0 desliga). Vale no estilo, no segmento ou no clipe. |
| `ritmo_corte` | Duração média de cada corte, em segundos (as referências usam 2 a 2,8). |
| `barra_progresso` | Barra amarela no topo que enche até o fim. Ajuda a retenção em vídeos mais longos. |

## Efeitos de interface (`efeitos`)
Elementos no estilo do HUD do GTA 6 que entram deslizando rápido, param seco e somem com um fade. Ficam por
cima do vídeo e por baixo da legenda. Use 1 ou 2 por segmento, onde reforçam a fala (não decore à toa).
```json
"efeitos": [{"tipo": "estrelas", "qtd": 3, "em": 0.3},
            {"tipo": "card", "titulo": "Veículo roubado", "sub": "SUV vermelha", "em": 0.4}]
```
Comuns a todos: `em` (segundos depois do início do segmento, padrão 0,15), `dur` ou `ate` (padrão ~2,4 s, sem passar
muito do segmento), `x`/`y` (centro do elemento, 0 a 1), `cor` (amarelo, rosa, verde, vermelho, laranja, branco ou
`#RRGGBB`) e `som` (outro som ou `false`).

| tipo | Parâmetros | Visual (posição padrão) |
|---|---|---|
| `card` | `titulo`, `sub` | Painel escuro com barra colorida: "VEÍCULO ROUBADO / SUV VERMELHA" (topo) |
| `aviso` | `texto` | Pílula de aviso do jogo com triângulo: "MOTOR DANIFICADO" (topo) |
| `texto` | `texto`, `tamanho` | Pílula de texto livre (topo) |
| `titulo` | `texto`, `tamanho` | Título grande inclinado com sublinhado: "GTA VI" (topo) |
| `fato` | `n`, `total` | Selo "FATO 3/10" com barra de progresso (canto superior esquerdo) |
| `numero` | `n`, `sub`, `tamanho` | Número gigante amarelo→laranja: "93" + "MILHÕES EM 24H" |
| `estrelas` | `qtd`, `total` (5) | Estrelas de procurado acendendo uma a uma, com som |
| `dinheiro` | `de`, `para` | Contador de dinheiro: verde subindo, vermelho caindo |
| `cronometro` | `de` (60) | Relógio circular em contagem regressiva com tique (canto superior direito) |
| `icone` | `simbolo`: `alerta`, `check`, `x`, `cifrao`, `proibido` | Ícone redondo pulsando (`alerta` = atalho para o ícone de alerta) |
| `moldura` | `x`, `y`, `w`, `h` (frações da tela) | Cantos amarelos fechando em volta de algo na imagem |
| `pin` | `x`, `y`, `texto` | Pino de mapa com etiqueta; a ponta fica em (x, y) |
| `rota` | `pontos` `[[x, y], ...]` | Linha verde que se desenha (use sobre o mapa) |
| `seta` | `dir`: `cima`, `baixo`, `esquerda`, `direita` | Seta amarela grossa dando empurrõezinhos |

Regras: elementos grandes no terço de cima (`y` 0,08 a 0,30), longe do rosto do personagem (≈ 0,35–0,55) e
da legenda (≈ 0,69). Não use `cartela` e um efeito de topo no mesmo segmento (ocupam o mesmo lugar).
Fatos e valores nos efeitos seguem a mesma regra do texto: nada inventado.

O áudio final sai normalizado em −14 LUFS, o padrão do TikTok/Reels/Shorts. A música abaixa sozinha quando a voz fala.

## Enquadramento (revisão obrigatória antes de renderizar)
O `montar.py` dá um palpite automático (rostos, pessoas, movimento, destaque), mas **erra com frequência**: rosto
no escuro ou contra a luz, objeto pequeno (avião, carro), duas pessoas. Por isso:
1. Rode a prévia (`previa.bat` ou `montar.py ... --so-plano`) e abra `out/previa_enquadramento.jpg`.
   Cada quadro mostra a janela (verde = tela cheia, azul = panorâmica, laranja = inteiro) e uma régua 0–1 em cima.
2. Para cada corte, pergunte: **o assunto da frase está inteiro dentro da janela?** O rosto em close, a pessoa que
   age, o veículo, a explosão. Se não estiver, leia na régua o valor do foco que centraliza o assunto.
3. Escreva as correções em `"enquadramento"` no roteiro.json, pelo número do corte que aparece na prévia:
   ```json
   "enquadramento": {"3": 0.15, "7": [0.05, 0.8], "12": "inteiro"}
   ```
   Número = foco fixo. Lista = panorâmica. `"inteiro"` = quadro todo. Para trocar a cena, mude `clipes`.
   Cena que não serve (escura demais, íntima, sem assunto) sai do roteiro e vai como `"ruim"` na biblioteca.
4. Rode a prévia de novo até tudo ficar certo e só então renderize. Os números dos cortes só mudam se o texto mudar.
