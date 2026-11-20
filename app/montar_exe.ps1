# Monta o instalador do Estudio GTA 6 (Setup_EstudioGTA6.exe). Chamado pelo ferramentas\montar_exe.bat.
# Tudo e registrado em <pasta>\instalador\montar_exe_log.txt
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$APPSRC = $PSScriptRoot                                   # ferramentas\app
$FERR   = Split-Path $APPSRC -Parent                      # ferramentas
$RAIZ   = Split-Path $FERR -Parent                        # skill-gta6
$SAIDA  = Join-Path $RAIZ "instalador"
$BUILD  = Join-Path $env:LOCALAPPDATA "EstudioGTA6_build" # fora do OneDrive (sao ~700 MB)
$PAC    = Join-Path $BUILD "pacote"
$PYVER  = "3.12.10"
New-Item -ItemType Directory -Force -Path $SAIDA | Out-Null
$LOG = Join-Path $SAIDA "montar_exe_log.txt"
Start-Transcript -Path $LOG -Force | Out-Null

function Passo($n, $t) { Write-Host ""; Write-Host "===== [$n/9] $t =====" -ForegroundColor Cyan }
function Baixar($url, $dest) {
  for ($i = 1; $i -le 3; $i++) {
    try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing; return }
    catch { Write-Host "  tentativa $i falhou: $($_.Exception.Message)"; Start-Sleep 3 }
  }
  throw "nao consegui baixar $url"
}
function Rodar($exe, [string[]]$argumentos) {
  # passa a saida (inclusive erros) pelo PowerShell para cair no log; erro = codigo de saida diferente de 0
  $antes = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  & $exe @argumentos 2>&1 | ForEach-Object { Write-Host "  $_" }
  $codigo = $LASTEXITCODE; $ErrorActionPreference = $antes
  if ($codigo -ne 0) { throw "falhou ($codigo): $exe $($argumentos -join ' ')" }
}

try {
  $versao = (Get-Content (Join-Path $FERR "VERSAO.txt") -Raw).Trim()
  Write-Host "Estudio GTA 6 - versao $versao"
  Write-Host "dados/ferramentas: $RAIZ"
  Write-Host "montagem em: $BUILD"

  Passo 1 "limpando a pasta de montagem"
  $pronto = "$BUILD\runtime_ok.txt"
  $reqHash = (Get-FileHash (Join-Path $APPSRC "requisitos.txt")).Hash
  $reusar = (Test-Path "$PAC\runtime\python.exe") -and (Test-Path $pronto) -and ((Get-Content $pronto -Raw).Trim() -eq $reqHash)
  if (Test-Path $PAC) {
    Get-ChildItem $PAC -Force | Where-Object { -not ($reusar -and $_.Name -eq "runtime") } | Remove-Item -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $PAC, "$PAC\runtime", "$PAC\bin", "$BUILD\cache" | Out-Null
  $py = "$PAC\runtime\python.exe"
  if ($reusar) { Write-Host "  reaproveitando o Python e os pacotes ja montados (passos 2-4)" }

  if (-not $reusar) {
  Passo 2 "Python $PYVER (embutido)"
  $zip = "$BUILD\cache\python-$PYVER-embed-amd64.zip"
  if (-not (Test-Path $zip)) { Baixar "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip" $zip }
  Expand-Archive -Path $zip -DestinationPath "$PAC\runtime" -Force
  Get-ChildItem "$PAC\runtime\*._pth" | Remove-Item -Force   # sem ._pth: Python normal (acha site-packages e a pasta do script)
  $py = "$PAC\runtime\python.exe"
  Rodar $py @("-c", "import sys; print(sys.version)")

  Passo 3 "pip"
  $gp = "$BUILD\cache\get-pip.py"
  if (-not (Test-Path $gp)) { Baixar "https://bootstrap.pypa.io/get-pip.py" $gp }
  Rodar $py @($gp, "--no-warn-script-location")

  Passo 4 "pacotes (OpenCV, voz, yt-dlp, deno, whisper, janela propria, bandeja) - demora alguns minutos"
  # pacotes que so existem como codigo-fonte: o build isolado do pip nao funciona no Python embutido,
  # entao instala setuptools/wheel e compila esses sem isolamento antes do resto
  Rodar $py @("-m", "pip", "install", "--no-warn-script-location", "--prefer-binary", "setuptools", "wheel")
  Rodar $py @("-m", "pip", "install", "--no-warn-script-location", "--no-build-isolation", "proxy_tools")
  Rodar $py @("-m", "pip", "install", "--no-warn-script-location", "--prefer-binary", "--no-build-isolation", "-r", (Join-Path $APPSRC "requisitos.txt"))
  Rodar $py @("-c", "import cv2, numpy, PIL, edge_tts, yt_dlp, pystray, deno, faster_whisper, webview, clr; print('pacotes ok (janela propria ok), OpenCV', cv2.__version__)")
  $reqHash | Out-File $pronto -Encoding ascii
  }

  Passo 5 "ffmpeg"
  $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
  $fp = (Get-Command ffprobe -ErrorAction SilentlyContinue).Source
  if ($ff -and $fp) {
    Copy-Item $ff, $fp "$PAC\bin\" -Force
    Get-ChildItem (Split-Path $ff) -Filter *.dll -ErrorAction SilentlyContinue | Copy-Item -Destination "$PAC\bin\" -Force
    Write-Host "  copiado de $(Split-Path $ff)"
  } else {
    $fz = "$BUILD\cache\ffmpeg.zip"
    if (-not (Test-Path $fz)) { Baixar "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $fz }
    Expand-Archive -Path $fz -DestinationPath "$BUILD\cache\ffmpeg" -Force
    Get-ChildItem "$BUILD\cache\ffmpeg" -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination "$PAC\bin\" -Force
  }
  Rodar "$PAC\bin\ffmpeg.exe" @("-hide_banner", "-version")

  Passo 6 "ferramentas, modelos e musicas"
  $dest = "$PAC\ferramentas_padrao"
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  foreach ($d in "scripts", "assets", "references", "app") {
    Copy-Item (Join-Path $FERR $d) $dest -Recurse -Force
  }
  Copy-Item (Join-Path $FERR "VERSAO.txt") $dest -Force
  # nunca leva chaves/segredos nem cache
  Get-ChildItem $dest -Recurse -Force -Include "__pycache__" -Directory | Remove-Item -Recurse -Force
  Get-ChildItem $dest -Recurse -Force -Include "config.json", "zernio.json", "app_log.txt", "cookies.txt" | Remove-Item -Force
  New-Item -ItemType Directory -Force -Path "$PAC\musicas_padrao" | Out-Null
  Get-ChildItem (Join-Path $RAIZ "musicas") -Include "tema_gta6*", "extra_gta6*" -File -Recurse -ErrorAction SilentlyContinue |
    Copy-Item -Destination "$PAC\musicas_padrao" -Force
  Copy-Item (Join-Path $APPSRC "iniciar.py"), (Join-Path $APPSRC "icone.ico") $PAC -Force
  # o Python do programa acha os modulos vizinhos do script (como o estudio.py faz com os outros scripts)?
  $t = "$BUILD\teste_import"; New-Item -ItemType Directory -Force -Path $t | Out-Null
  "VALOR = 'ok'" | Out-File "$t\vizinho.py" -Encoding ascii
  "import vizinho; print('import de modulo vizinho:', vizinho.VALOR)" | Out-File "$t\principal.py" -Encoding ascii
  Rodar $py @("$t\principal.py")
  Rodar $py @("-c", "import cv2; n=cv2.dnn.readNet(r'$dest\assets\modelos\object_detection_yolox_2022nov.onnx'); print('detector de objetos ok')")

  Passo 7 "EstudioGTA6.exe (lancador)"
  $csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
  if (-not (Test-Path $csc)) { $csc = "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe" }
  Rodar $csc @("/nologo", "/target:winexe", "/optimize+", "/win32icon:$APPSRC\icone.ico", "/r:System.Windows.Forms.dll",
               "/out:$PAC\EstudioGTA6.exe", "$APPSRC\lancador.cs")

  Passo 8 "Inno Setup (gerador do instalador)"
  function AcharISCC {
    @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
      "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
      "$env:ProgramFiles\Inno Setup 7\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe") |
      Where-Object { Test-Path $_ } | Select-Object -First 1
  }
  $iscc = AcharISCC
  if (-not $iscc) {
    Write-Host "  instalando o Inno Setup pelo winget..."
    $antes = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & winget install --id JRSoftware.InnoSetup -e -s winget --silent --accept-package-agreements --accept-source-agreements 2>&1 |
      ForEach-Object { Write-Host "  $_" }
    $ErrorActionPreference = $antes
    $iscc = AcharISCC
  }
  if (-not $iscc) {
    Write-Host "  winget nao resolveu; baixando o instalador oficial..."
    $is = "$BUILD\cache\innosetup.exe"
    $urls = @("https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe",
              "https://files.jrsoftware.org/is/6/innosetup-6.7.4.exe",
              "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe",
              "https://files.jrsoftware.org/is/6/innosetup-6.7.3.exe")
    $ok = $false
    foreach ($u in $urls) { try { Baixar $u $is; $ok = $true; break } catch { Write-Host "  $u nao deu" } }
    if (-not $ok) { throw "nao consegui baixar o Inno Setup. Instale manualmente em https://jrsoftware.org/isdl.php e rode de novo" }
    Start-Process $is -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER" -Wait
    $iscc = AcharISCC
    if (-not $iscc) { throw "Inno Setup nao instalou" }
  }
  Write-Host "  $iscc"

  Passo 9 "gerando Setup_EstudioGTA6.exe (comprimindo ~700 MB, pode levar 5-15 min)"
  Rodar $iscc @("/Q", "/DPacote=$PAC", "/DVersao=$versao", "/DSaida=$SAIDA", "$APPSRC\instalador.iss")
  $setup = Join-Path $SAIDA "Setup_EstudioGTA6.exe"
  $mb = [math]::Round((Get-Item $setup).Length / 1MB)
  Write-Host ""
  Write-Host "PRONTO: $setup ($mb MB)" -ForegroundColor Green
  "PRONTO $versao $mb MB" | Out-File (Join-Path $SAIDA "status.txt") -Encoding utf8
}
catch {
  Write-Host ""
  Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
  "ERRO: $($_.Exception.Message)" | Out-File (Join-Path $SAIDA "status.txt") -Encoding utf8
}
finally {
  Stop-Transcript | Out-Null
}
