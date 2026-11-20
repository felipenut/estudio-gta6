# Publica a pasta "ferramentas" no GitHub para o Estudio GTA 6 se atualizar sozinho nos PCs.
#
#   Primeira vez (cria o repositorio e liga a atualizacao automatica):
#     powershell -ExecutionPolicy Bypass -File ferramentas\app\publicar.ps1 -Primeira -Repo estudio-gta6 -Mensagem "primeira versao"
#   Toda atualizacao depois:
#     powershell -ExecutionPolicy Bypass -File ferramentas\app\publicar.ps1 -Mensagem "o que mudou"
#
# O que faz: confere a sintaxe de todo .py, garante que nenhuma chave vai junto, sobe o VERSAO.txt
# (AAAA.M.D.N, sempre maior que o atual), faz commit e push. O programa de quem tem o Estudio ve o
# VERSAO.txt novo no GitHub ao abrir, baixa e aplica sozinho (ferramentas/scripts/atualizar.py).
# Precisa: git e (so na primeira vez) GitHub CLI "gh" logado (gh auth login).
param(
  [string]$Repo = "",
  [string]$Mensagem = "",
  [switch]$Primeira,
  [switch]$Privado,
  [switch]$SemSubirVersao
)
$ErrorActionPreference = "Stop"
$FERR = Split-Path $PSScriptRoot -Parent
Set-Location $FERR
$UTF8 = New-Object System.Text.UTF8Encoding $false          # sem BOM (o atualizador le numeros)
function Falha($m) { Write-Host "`nERRO: $m" -ForegroundColor Red; exit 1 }
function Ok($m) { Write-Host $m -ForegroundColor Green }
function Escrever($arq, $txt) { [System.IO.File]::WriteAllText((Join-Path $FERR $arq), $txt, $UTF8) }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Falha "git nao encontrado. Instale: winget install Git.Git" }

# --- 1. Python para conferir a sintaxe (o do programa instalado, ou o do sistema)
$py = Join-Path $env:LOCALAPPDATA "Programs\Estudio GTA 6\runtime\python.exe"
$pyArgs = @()
if (-not (Test-Path $py)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py"; $pyArgs = @("-3") }
  elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
  else { $py = $null }
}
if ($py) {
  Write-Host "Conferindo a sintaxe dos scripts..."
  $chk = "import sys,pathlib`nerros=[]`nfor f in pathlib.Path('scripts').rglob('*.py'):`n    try: compile(f.read_bytes(), str(f), 'exec')`n    except SyntaxError as e: erros.append(f'{f}:{e.lineno}: {e.msg}')`nprint('\n'.join(erros)); sys.exit(1 if erros else 0)"
  & $py @pyArgs -c $chk
  if ($LASTEXITCODE -ne 0) { Falha "ha erro de sintaxe (acima). Nada foi publicado." }
} else { Write-Host "Aviso: Python nao encontrado, pulei a conferencia de sintaxe." -ForegroundColor Yellow }

# --- 2. repositorio git local
if (-not (Test-Path (Join-Path $FERR ".git"))) {
  git init -q -b main | Out-Null
  Ok "Repositorio git criado em $FERR"
}
git config core.autocrlf false | Out-Null

# --- 3. primeira vez: cria no GitHub e grava atualizacao.json
$temRemoto = (git remote) -contains "origin"
if ($Primeira -or -not $temRemoto) {
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Falha "GitHub CLI nao encontrado. Instale: winget install GitHub.cli  e depois: gh auth login" }
  gh auth status 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { Falha "faca login no GitHub primeiro: gh auth login" }
  gh auth setup-git 2>$null | Out-Null                         # o git push usa o mesmo login do gh
  if (-not $Repo) { $Repo = "estudio-gta6" }
  if ($Repo -notmatch "/") { $dono = (gh api user --jq .login).Trim(); $Repo = "$dono/$Repo" }
  $cfg = [ordered]@{ repo = $Repo; ramo = "main"; automatico = $true }
  Escrever "atualizacao.json" (($cfg | ConvertTo-Json) + "`n")
  if (-not $temRemoto) {
    $vis = if ($Privado) { "--private" } else { "--public" }
    gh repo create $Repo $vis --description "Estudio GTA 6 Shorts - ferramentas (atualizacao automatica)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Falha "nao consegui criar $Repo no GitHub (ja existe? use outro nome com -Repo)" }
    git remote add origin "https://github.com/$Repo.git"
    Ok "Repositorio criado: https://github.com/$Repo"
  }
  if ($Privado) { Write-Host "Repositorio PRIVADO: em cada PC, crie ferramentas\github_token.txt com um token de leitura (fine-grained, Contents: Read-only)." -ForegroundColor Yellow }
}

# --- 4. ha algo para publicar?
$mudancas = git status --porcelain
if (-not $mudancas -and -not $Primeira) { Ok "Nada mudou desde a ultima publicacao. Nada a fazer."; exit 0 }

# --- 5. sobe a versao (AAAA.M.D.N, sempre maior que a atual)
$atual = ""
if (Test-Path "VERSAO.txt") { $atual = ([System.IO.File]::ReadAllText((Join-Path $FERR "VERSAO.txt"))).Trim().TrimStart([char]0xFEFF) }
$hoje = "{0}.{1}.{2}" -f (Get-Date).Year, (Get-Date).Month, (Get-Date).Day
if ($SemSubirVersao -and $atual) { $nova = $atual }
else {
  $n = 1
  if ($atual.StartsWith("$hoje.")) { $n = [int]($atual.Substring($hoje.Length + 1)) + 1 }
  $nova = "$hoje.$n"
  $pa = $atual.Split("."); $pn = $nova.Split(".")
  for ($i = 0; $i -lt [Math]::Max($pa.Length, $pn.Length); $i++) {          # nunca regredir
    $a = if ($i -lt $pa.Length) { [int]$pa[$i] } else { 0 }; $b = if ($i -lt $pn.Length) { [int]$pn[$i] } else { 0 }
    if ($b -gt $a) { break }
    if ($b -lt $a) { $nova = "$atual.1"; break }
  }
  Escrever "VERSAO.txt" "$nova`n"
}
Ok "Versao: $atual -> $nova"

# --- 6. commit (com trava contra chaves) e push
git add -A
$proibidos = @("config.json", "zernio.json", "variacao.json", "primeira_config.json", "github_token.txt", "app_log.txt", "_atualizacao.json")
$vazou = git diff --cached --name-only | Where-Object { $proibidos -contains (Split-Path $_ -Leaf) -or $_ -like "_backup/*" }
if ($vazou) { git reset -q; Falha "arquivos com chaves/dados iam junto: $($vazou -join ', '). Confira o .gitignore. Nada foi publicado." }
if (-not $Mensagem) { $Mensagem = "atualizacao" }
git commit -q -m "v${nova}: $Mensagem"
if ($LASTEXITCODE -ne 0) { Falha "o commit falhou (veja acima)" }
git push -u origin main
if ($LASTEXITCODE -ne 0) { Falha "o push falhou (internet? login? rode: gh auth login)" }
$repoUrl = (git remote get-url origin)
Ok "`nPublicado: versao $nova em $repoUrl"
Write-Host "Os programas instalados baixam esta versao na proxima vez que abrirem."
