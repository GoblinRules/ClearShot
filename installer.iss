; ClearShot Installer Script for Inno Setup

#define MyAppName "ClearShot"
#define MyAppVersion "1.3.13"
#define MyAppPublisher "GoblinRules"
#define MyAppURL "https://github.com/GoblinRules/ClearShot"
#define MyAppExeName "ClearShot.exe"
#define MyAppDescription "Lightweight screenshot tool for Windows"

[Setup]
AppId={{A7D12F3E-8B4C-4E5A-9F6D-1C2E3A4B5D6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=ClearShot_Setup_{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\ClearShot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Check: ShouldCreateDesktopIcon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function OpenEvent(Access: LongWord; Inherit: Boolean; Name: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(Event: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ShutdownEvent: THandle;
  Attempts: Integer;
begin
  Result := '';
  ShutdownEvent := OpenEvent($0002, False, 'ClearShot_Shutdown_Event');
  if ShutdownEvent <> 0 then
  begin
    SetEvent(ShutdownEvent);
    CloseHandle(ShutdownEvent);
    for Attempts := 1 to 100 do
    begin
      if not CheckForMutexes('ClearShot_SingleInstance_Mutex') then
        Exit;
      Sleep(100);
    end;
  end;
  if CheckForMutexes('ClearShot_SingleInstance_Mutex') then
    Result := 'ClearShot is still running. Finish any recording and choose Exit from its tray menu, then retry.';
end;

function ShouldCreateDesktopIcon(): Boolean;
begin
  Result := not WizardSilent;
end;
