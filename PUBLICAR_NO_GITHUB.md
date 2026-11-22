# Publicar no GitHub e atualizar o Estúdio sozinho

O repositório do GitHub é **a pasta `ferramentas/`** (só código, página, referências e o instalador).
Cada programa instalado confere esse repositório **ao abrir**. Se o `VERSAO.txt` de lá for maior que o do PC,
ele baixa, confere (todo `.py` precisa compilar e a versão do zip tem que bater), guarda uma cópia do que vai mudar
em `ferramentas/_backup/<versão antiga>/`, aplica e reabre já na versão nova. Quem faz isso é
`scripts/atualizar.py`, chamado pelo `scripts/app.py` antes da janela abrir. Chaves e preferências
(`config.json`, `zernio.json`, `variacao.json`, `primeira_config.json`, `atualizacao.json`, `github_token.txt`) nunca
são sobrescritas, e nenhum arquivo local é apagado.

## Primeira vez (uma vez só)

Pré-requisitos no Windows: `winget install Git.Git` e `winget install GitHub.cli`, depois `gh auth login`.

```bat
cd C:\Users\felip\OneDrive\Desktop\skill-gta6\ferramentas
publicar.bat primeira
```

O script:
1. confere a sintaxe de todos os `.py`;
2. cria o repositório git em `ferramentas/` (ramo `main`);
3. cria `seu-usuario/estudio-gta6` no GitHub (**público** por padrão: não há chave nenhuma no código,
   o `.gitignore` e uma trava no script impedem);
4. grava `atualizacao.json` com o nome do repositório (é isso que liga a atualização automática);
5. sobe o `VERSAO.txt`, faz commit e push.

Repositório privado: `powershell -ExecutionPolicy Bypass -File app\publicar.ps1 -Primeira -Repo estudio-gta6 -Privado`.
Aí cada PC precisa de `ferramentas\github_token.txt` com um token *fine-grained* só de leitura
(Repository access: este repo; Permissions: Contents → Read-only).

## Toda atualização

```bat
cd C:\Users\felip\OneDrive\Desktop\skill-gta6\ferramentas
publicar.bat
```
(ou `powershell -ExecutionPolicy Bypass -File app\publicar.ps1 -Mensagem "o que mudou"`)

A versão passa a ser `AAAA.M.D.N` (ex.: `2026.11.20.1`, `2026.11.20.2`…), sempre maior que a anterior.
**Não edite o `VERSAO.txt` à mão para publicar**: o script cuida disso, e o programa compara números.

## Regras para quem publica (Codex, Claude ou pessoa)

- Nunca use `git add -f` em arquivos do `.gitignore`. O script recusa o commit se uma chave entrar.
- Não publique código que não rodou: rode antes os testes do `AGENTS.md` (§9). O atualizador também recusa
  zip com erro de sintaxe, mas um erro de lógica chega a todos os PCs.
- Mudou a API entre página e servidor: suba `VERSAO` em `scripts/estudio.py` e `VERSAO_PAGINA` em
  `scripts/estudio.html` juntos.
- Pacote Python novo não chega pelo atualizador (ele só troca arquivos). Coloque em `app/requisitos.txt`,
  gere um instalador novo (`montar_exe.bat`) e avise que é preciso reinstalar.
- Voltar uma versão: os arquivos antigos estão em `ferramentas/_backup/<versão>/`. Para desfazer para todos,
  reverta o commit (`git revert`) e publique de novo: a versão sobe e o código antigo volta.

## Conferir à mão

```bat
cd C:\Users\felip\OneDrive\Desktop\skill-gta6
"%LOCALAPPDATA%\Programs\Estudio GTA 6\runtime\python.exe" ferramentas\scripts\atualizar.py verificar
```
No programa: **Ajustes e skill → Atualizações automáticas → Procurar agora**.
Último resultado: `ferramentas/_atualizacao.json`. Para pular a checagem uma vez: variável `GTA6_SEM_ATUALIZAR=1`.
