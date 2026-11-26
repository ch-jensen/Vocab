; Inno Setup script for the Vocab installer.
;
;     iscc packaging\vocab.iss            (after: pyinstaller packaging\vocab.spec)
;     iscc /DAppVersion=0.2.0 packaging\vocab.iss
;
; Produces dist\VocabSetup-<version>.exe. Installs for the current user only, so no
; administrator rights are needed. The user's progress (%APPDATA%\Vocab) is never
; touched by installing, updating or uninstalling.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F1C2A7E-3B8D-4E59-9A1F-5C7D2E8B4A10}
AppName=Vocab
AppVersion={#AppVersion}
AppVerName=Vocab {#AppVersion}
AppPublisher=Vocab
AppPublisherURL=https://github.com/ch-jensen/Vocab
DefaultDirName={autopf}\Vocab
DefaultGroupName=Vocab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=VocabSetup-{#AppVersion}
SetupIconFile=vocab.ico
UninstallDisplayIcon={app}\Vocab.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=LICENSES.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Vocab\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Vocab"; Filename: "{app}\Vocab.exe"
Name: "{group}\{cm:UninstallProgram,Vocab}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Vocab"; Filename: "{app}\Vocab.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Vocab.exe"; Description: "{cm:LaunchProgram,Vocab}"; Flags: nowait postinstall skipifsilent
