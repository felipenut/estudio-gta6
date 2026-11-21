# Biblioteca de clipes

Fica em `biblioteca/`: os vídeos em `biblioteca/videos/`, o índice em `biblioteca/biblioteca.json` e as miniaturas em `biblioteca/miniaturas/`.

## O que ter na biblioteca (comece por aqui)
1. Trailer 1 e Trailer 2 oficiais do GTA 6 (canal Rockstar Games), na maior qualidade disponível.
2. Gameplay oficial, vídeos e screenshots publicados pela Rockstar (site rockstargames.com/VI), mais o trailer de lançamento, se houver.
3. Gameplay de GTA V sem HUD e sem facecam, para comparações.
4. Opcional: mapas (fan maps), vista aérea, cenas de perseguição e física.
Evite vídeos com marca d'água de outros criadores, facecam ou narração por cima.

Jeito mais fácil: dois cliques em `ferramentas\montar_biblioteca.bat`. Ele instala as dependências, baixa todos os
vídeos de GTA VI do canal oficial da Rockstar, divide tudo em cenas e gera as miniaturas. O progresso fica em
`biblioteca\status.txt` e `biblioteca\log.txt`. Pode rodar de novo quando sair vídeo novo, porque só baixa o que falta.

Comandos avulsos (a partir da pasta skill-gta6):
```
python ferramentas/scripts/baixar.py oficiais
python ferramentas/scripts/baixar.py pesquisar "gta 6 trailer 2 rockstar games"
python ferramentas/scripts/baixar.py baixar https://youtu.be/XXXX
python ferramentas/scripts/baixar.py baixar https://youtu.be/XXXX --trecho 01:10-01:40
python ferramentas/scripts/biblioteca.py indexar biblioteca/videos
```

## Etiquetar (Claude faz)
O `indexar` divide cada vídeo em cenas de 1,2 a 6 s e gera folhas de miniaturas (`<video>_folha_N.jpg`),
com o número da cena e o tempo de início. Para etiquetar:
1. Rode `biblioteca.py pendentes` para ver quais folhas faltam.
2. Abra cada folha com Read. No modo PC, traga a imagem com device_stage_files.
3. Escreva um `tags_lote.json` para cada folha e aplique com
   `python ferramentas/scripts/biblioteca.py marcar tags_lote.json --lib biblioteca/biblioteca.json`:
   ```json
   {"GTA6_Trailer_1#12": {"d": "Lucia no supino da academia da prisão", "t": ["lucia","academia","prisao","close"], "foco": 0.45},
    "GTA6_Trailer_1#13": ["carro na avenida à noite com neon", ["carro","noite","neon","vice city"]],
    "GTA6_Trailer_1#14": "ruim"}
   ```
   `descricao`: curta e concreta (quem, o quê, onde, clima). `tags`: 5 a 8, minúsculas, sem acento.
   `foco`: posição horizontal do assunto (0 a 1), quando ele não está no centro.
4. `"ruim"` descarta a cena (cartela de texto, transição, borrão). Telas pretas e quadros chapados já saem
   marcados como ruim pelo `indexar` (na folha aparecem com "X"). Confira se ele não descartou alguma cena boa e escura.
   A busca e a escolha automática ignoram cenas ruins.

Vocabulário de tags, para manter consistência:
- personagens: `jason`, `lucia`, `npc`, `policia`, `gangue`
- lugares: `vice city`, `leonida`, `praia`, `keys`, `pantano`, `estrada`, `cidade`, `balada`, `academia`, `loja`, `mapa`
- ação: `carro`, `perseguicao`, `assalto`, `tiro`, `explosao`, `fuga`, `danca`, `festa`, `animal`, `jacare`, `barco`, `aviao`, `moto`
- clima e luz: `dia`, `noite`, `por do sol`, `chuva`, `tempestade`
- tipo: `logo`, `close`, `paisagem`, `vista aerea`, `comparacao`, `gta5`, `entrevista`, `noticia`, `meme`, `humor`
