# Move a pasta de dados do Estúdio GTA 6 para fora do OneDrive (copia tudo, confere e aponta o programa para a nova).
$ErrorActionPreference = "Stop"
$origem = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Write-Host ""
Write-Host "=== Mover a pasta de dados do Estudio GTA 6 ===" -ForegroundColor Cyan
Write-Host "Pasta atual: $origem"
$aberto = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($aberto) {
  Write-Host ""
  Write-Host "O Estudio esta aberto. Feche: icone perto do relogio > Sair. Depois rode este arquivo de novo." -ForegroundColor Yellow
  exit 1
}
$padrao = "C:\skill-gta6"
$destino = Read-Host "Nova pasta (Enter = $padrao)"
if ([string]::IsNullOrWhiteSpace($destino)) { $destino = $padrao }
$destino = $destino.Trim().Trim('"').TrimEnd('\')
if ($destino.ToLower().Contains("onedrive")) { Write-Host "Escolha uma pasta fora do OneDrive." -ForegroundColor Yellow; exit 1 }
if ($destino.ToLower().StartsWith($origem.ToLower())) { Write-Host "A nova pasta nao pode ficar dentro da atual." -ForegroundColor Yellow; exit 1 }
if ((Test-Path $destino) -and (Get-ChildItem $destino -Force | Select-Object -First 1)) {
  Write-Host "A pasta $destino ja existe e nao esta vazia. Escolha outra." -ForegroundColor Yellow; exit 1
}
$tam = (Get-ChildItem $origem -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
$disco = (Get-PSDrive -Name $destino.Substring(0,1)).Free
Write-Host ("Tamanho: {0:N1} GB  |  livre no disco {1}: {2:N1} GB" -f ($tam/1GB), $destino.Substring(0,2), ($disco/1GB))
if ($disco -lt $tam * 1.05) { Write-Host "Espaco insuficiente no disco de destino." -ForegroundColor Red; exit 1 }
Write-Host "Copiando (arquivos que estao so na nuvem serao baixados; pode demorar)..."
robocopy "$origem" "$destino" /E /R:2 /W:2 /XJ /NFL /NDL /NP /NJH | Out-Host
if ($LASTEXITCODE -ge 8) { Write-Host "ERRO na copia (robocopy $LASTEXITCODE). Nada foi alterado." -ForegroundColor Red; exit 1 }
$n1 = (Get-ChildItem $origem -Recurse -File -Force -ErrorAction SilentlyContinue).Count
$n2 = (Get-ChildItem $destino -Recurse -File -Force -ErrorAction SilentlyContinue).Count
if ($n2 -lt $n1) { Write-Host "ERRO: copiados $n2 de $n1 arquivos. Nada foi alterado." -ForegroundColor Red; exit 1 }
$prog = Join-Path $env:LOCALAPPDATA "Programs\Estudio GTA 6"
if (Test-Path $prog) {
  [System.IO.File]::WriteAllText((Join-Path $prog "pasta_dados.txt"), $destino + "`r`n", (New-Object System.Text.UTF8Encoding $true))
}
$local = Join-Path $env:LOCALAPPDATA "EstudioGTA6"
New-Item -ItemType Directory -Force $local | Out-Null
[System.IO.File]::WriteAllText((Join-Path $local "pasta_dados.txt"), $destino + "`r`n", (New-Object System.Text.UTF8Encoding $true))
$aviso = "Esta pasta foi copiada para $destino em $(Get-Date -Format 'dd/MM/yyyy HH:mm'). O Estudio agora usa a nova. Depois de conferir que esta tudo la, pode apagar esta pasta."
[System.IO.File]::WriteAllText((Join-Path $origem "PASTA_MOVIDA_LEIA.txt"), $aviso, (New-Object System.Text.UTF8Encoding $true))
Write-Host ""
Write-Host "PRONTO: $n2 arquivos em $destino" -ForegroundColor Green
Write-Host "1. Abra o Estudio (atalho Estudio GTA 6)."
Write-Host "2. No app do Claude, conecte a pasta nova ($destino) e, no Estudio, Ajustes e skill > Gerar de novo > envie a mensagem ao Claude."
Write-Host "3. Confira os videos no Estudio e depois apague a pasta antiga: $origem"
exit 0
