#ifndef AppVersion
#define AppVersion "2.0.0"
#endif
#ifndef BundleDir
#define BundleDir "..\dist\v2\VideoDownloader"
#endif
#ifndef ReleaseDir
#define ReleaseDir "..\..\release\v2.0.0"
#endif
#ifndef SetupAppId
#define SetupAppId "{{734095DC-442F-45DA-AD73-7F3B52741394}"
#endif
#ifndef SettingsRegistryKey
#define SettingsRegistryKey "Software\LocalVideoDownloader"
#endif
#ifndef SettingsSubdir
#define SettingsSubdir "LocalVideoDownloader"
#endif
[Setup]
AppId={#SetupAppId}
AppName=视频下载器
AppVersion={#AppVersion}
AppPublisher=Local Video Downloader
DefaultDirName={localappdata}\Programs\VideoDownloader
DefaultGroupName=视频下载器
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=VideoDownloader-Windows-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\VideoDownloader.exe
#ifdef QaInstall
Compression=none
SolidCompression=no
#else
Compression=lzma2/normal
SolidCompression=yes
#endif
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
LicenseFile=THIRD_PARTY.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"

[Tasks]
#ifndef QaInstall
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
#endif

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Legacy bundles accidentally carried tool-specific copies of Windows APIs.
; Remove only these known runtime DLLs so an in-place upgrade uses Windows 10/11.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt*.dll"
Type: files; Name: "{app}\_internal\ucrtbase.dll"
Type: files; Name: "{app}\_internal\api-ms-win-*.dll"
Type: files; Name: "{app}\_internal\Qt6*.dll"
Type: files; Name: "{app}\_internal\MSVCP140*.dll"
; These retired Python 3.14 extensions otherwise become empty namespace
; packages under Python 3.12 and shadow the new application's imports.
Type: filesandordirs; Name: "{app}\_internal\brotlicffi"
Type: filesandordirs; Name: "{app}\_internal\bcrypt"
Type: filesandordirs; Name: "{app}\_internal\cryptography"
Type: filesandordirs; Name: "{app}\_internal\markupsafe"
Type: filesandordirs; Name: "{app}\_internal\websockets"

[Icons]
#ifndef QaInstall
Name: "{group}\视频下载器"; Filename: "{app}\VideoDownloader.exe"
Name: "{autodesktop}\视频下载器"; Filename: "{app}\VideoDownloader.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\VideoDownloader.exe"; Description: "打开视频下载器"; Flags: nowait postinstall skipifsilent

[Code]
var
  VideoDirectoryPage: TInputDirWizardPage;
  FirstInstallation: Boolean;

procedure InitializeWizard;
var
  InitialDirectory: String;
begin
  FirstInstallation :=
    (not FileExists(ExpandConstant('{localappdata}\{#SettingsSubdir}\settings.json'))) and
    (not RegValueExists(HKCU64, '{#SettingsRegistryKey}', 'InitialOutputDirectory'));
  VideoDirectoryPage := CreateInputDirPage(wpSelectDir,
    '选择视频下载位置', '视频和图片保存在哪里？',
    '安装后也可以在软件设置中更改，已有作品会自动迁移。', False, '');
  VideoDirectoryPage.Add('视频下载位置：');
  InitialDirectory := ExpandConstant('{param:VIDEODIR|}');
  if InitialDirectory = '' then
    InitialDirectory := AddBackslash(GetEnv('USERPROFILE')) + 'Videos\视频下载器\video';
  VideoDirectoryPage.Values[0] := InitialDirectory;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = VideoDirectoryPage.ID) and (not FirstInstallation);
end;

function ValidVideoDirectory: Boolean;
var
  Directory, ApplicationDirectory: String;
begin
  Directory := RemoveBackslashUnlessRoot(Trim(VideoDirectoryPage.Values[0]));
  ApplicationDirectory := AddBackslash(Lowercase(ExpandConstant('{app}')));
  Result := (ExtractFileDrive(Directory) <> '') and
    (Length(Directory) > Length(ExtractFileDrive(Directory)) + 1) and
    (Pos(ApplicationDirectory, AddBackslash(Lowercase(Directory))) <> 1);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = VideoDirectoryPage.ID) and (not ValidVideoDirectory) then
  begin
    MsgBox('请选择独立的视频文件夹，不要使用磁盘根目录或软件安装目录。', mbError, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FirstInstallation and (not ValidVideoDirectory) then
    Result := '视频下载位置无效，请选择独立的视频文件夹。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and FirstInstallation then
  begin
    if not RegWriteStringValue(HKCU64, '{#SettingsRegistryKey}', 'InitialOutputDirectory',
      RemoveBackslashUnlessRoot(Trim(VideoDirectoryPage.Values[0]))) then
      RaiseException('无法保存视频下载位置。');
  end;
end;
