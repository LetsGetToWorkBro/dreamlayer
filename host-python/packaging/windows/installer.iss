; installer.iss — the DreamLayer Brain Windows installer (Inno Setup 6).
;
;     iscc /DAppVersion=0.5.0 installer.iss
;     -> Output\DreamLayer-Setup.exe
;
; Expects dist\DreamLayer\ (the PyInstaller one-dir build from
; DreamLayer.spec) next to this script. Inno Setup over WiX/MSI because the
; whole ask is "copy a folder per-user, Start-menu entry, optional
; start-at-login, clean uninstall" — a 60-line .iss does that without an
; admin prompt, component GUIDs, or a toolchain beyond the compiler GitHub
; runners already ship.
;
; Per-user on purpose: installs under %LOCALAPPDATA%\Programs, needs no
; elevation, and the start-at-login task writes the same HKCU Run value the
; tray's --install-login writes (value name "DreamLayer"), so the installer
; checkbox and the CLI flag manage one entry. Uninstall removes the app and
; that Run value but leaves ~\.dreamlayer (your settings, index, history) in
; place — stated to the user on the way out.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E4B1A52-9C51-4E86-A32C-DL0000000001}
AppName=DreamLayer
AppVersion={#AppVersion}
AppPublisher=DreamLayer
AppPublisherURL=https://dreamlayer.app
DefaultDirName={userpf}\DreamLayer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=DreamLayer-Setup
SetupIconFile=dreamlayer.ico
UninstallDisplayIcon={app}\DreamLayer.exe
ArchitecturesInstallIn64BitMode=x64compatible
SolidCompression=yes
Compression=lzma2

[Tasks]
Name: "startup"; Description: "Start DreamLayer when you sign in (the always-on Brain your phone pairs with)"

[Files]
Source: "dist\DreamLayer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\DreamLayer"; Filename: "{app}\DreamLayer.exe"

[Registry]
; the same value the tray's --install-login manages; uninsdeletevalue keeps
; the uninstall clean
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "DreamLayer"; ValueData: """{app}\DreamLayer.exe"""; \
  Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\DreamLayer.exe"; Description: "Launch DreamLayer now"; \
  Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { the uninstaller never touches user data — say so, honestly }
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('DreamLayer was removed.' + #13#10 + #13#10 +
           'Your Brain data — settings, index, history — was left in place at '
           + ExpandConstant('{%USERPROFILE}') + '\.dreamlayer' + #13#10 +
           'Delete that folder too if you want a clean slate.',
           mbInformation, MB_OK);
end;
