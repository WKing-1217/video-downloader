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
