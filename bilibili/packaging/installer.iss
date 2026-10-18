#ifndef AppVersion
#define AppVersion "1.0.2"
#endif
[Setup]
AppId={{734095DC-442F-45DA-AD73-7F3B52741394}
AppName=视频下载器
AppVersion={#AppVersion}
AppPublisher=Local Video Downloader
DefaultDirName={localappdata}\Programs\VideoDownloader
DefaultGroupName=视频下载器
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\release
OutputBaseFilename=VideoDownloader-Windows-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\VideoDownloader.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
LicenseFile=THIRD_PARTY.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
Source: "..\dist\VideoDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\视频下载器"; Filename: "{app}\VideoDownloader.exe"
Name: "{autodesktop}\视频下载器"; Filename: "{app}\VideoDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoDownloader.exe"; Description: "打开视频下载器"; Flags: nowait postinstall skipifsilent
