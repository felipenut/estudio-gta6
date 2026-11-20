; Instalador do Estúdio GTA 6 (Inno Setup 6). Gerado pelo montar_exe.ps1 - não precisa abrir à mão.
#ifndef Pacote
  #define Pacote "pacote"
#endif
#ifndef Versao
  #define Versao "1.0"
#endif
#ifndef Saida
  #define Saida "."
#endif

[Setup]
AppId={{6A1E2C47-9C1B-4F7A-9E1D-6E5A7B3C2D10}
AppName=Estúdio GTA 6
AppVersion={#Versao}
AppPublisher=Estúdio GTA 6 Shorts
DefaultDirName={localappdata}\Programs\Estudio GTA 6
DefaultGroupName=Estúdio GTA 6
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={#Saida}
OutputBaseFilename=Setup_EstudioGTA6
SetupIconFile={#Pacote}\icone.ico
UninstallDisplayIcon={app}\EstudioGTA6.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#Pacote}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Estúdio GTA 6"; Filename: "{app}\EstudioGTA6.exe"; IconFilename: "{app}\icone.ico"
Name: "{group}\Desinstalar Estúdio GTA 6"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Estúdio GTA 6"; Filename: "{app}\EstudioGTA6.exe"; IconFilename: "{app}\icone.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\EstudioGTA6.exe"; Description: "Abrir o Estúdio GTA 6 agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\pasta_dados.txt"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\__pycache__"

[Code]
var
  PaginaDados: TInputDirWizardPage;

function PastaAnterior(): String;
var
  Linhas: TArrayOfString;
begin
  Result := ExpandConstant('{userdocs}\Estudio GTA 6');
  if DirExists(ExpandConstant('{userdesktop}\skill-gta6\ferramentas')) then
    Result := ExpandConstant('{userdesktop}\skill-gta6');
  if LoadStringsFromFile(ExpandConstant('{localappdata}\Programs\Estudio GTA 6\pasta_dados.txt'), Linhas) then
    if GetArrayLength(Linhas) > 0 then
      if Trim(Linhas[0]) <> '' then
        Result := Trim(Linhas[0]);
end;

procedure InitializeWizard;
begin
  PaginaDados := CreateInputDirPage(wpSelectDir, 'Pasta de dados',
    'Onde ficam a biblioteca de cenas, os vídeos, as músicas e as ferramentas?',
    'Se você já usa o Estúdio, escolha a pasta atual (a que tem biblioteca, videos e ferramentas). ' +
    'Nada nessa pasta é apagado: a instalação só acrescenta o que faltar. Desinstalar o programa não apaga os seus dados.',
    False, '');
  PaginaDados.Add('');
  PaginaDados.Values[0] := PastaAnterior();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Linhas: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    SetArrayLength(Linhas, 1);
    Linhas[0] := PaginaDados.Values[0];
    ForceDirectories(PaginaDados.Values[0]);
    SaveStringsToUTF8File(ExpandConstant('{app}\pasta_dados.txt'), Linhas, False);
  end;
end;
