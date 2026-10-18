# 视频下载器

Windows v2.0 使用原生 Qt 三页界面：粘贴即下载、下载即入库、点击卡片即可本地预览。自动识别 Bilibili、抖音和 X，保留当前权限下最高可用画质与音质，支持抖音图文、实况及配乐。

## 下载

- [Windows 安装包](https://github.com/WKing-1217/video-downloader/releases/latest/download/VideoDownloader-Windows-Setup.exe)：Windows 10 / 11 x64，内置运行环境、FFmpeg、播放与网页登录组件。
- [Android APK](https://github.com/WKing-1217/video-downloader/releases/latest/download/VideoDownloader-Android.apk)：Android 10+，ARM64 / x86_64，本次保持 v1.0.4。
- [最新版本与更新说明](https://github.com/WKing-1217/video-downloader/releases/latest)。

安装到原目录即可升级，无需卸载。Windows 与 Android 分别记录实际版本，固定安装包文件名；历史正式 Release 保留供恢复。

![Windows 界面](docs/desktop.png)

## 使用

在下载页输入框 Ctrl+V、右键粘贴或点击粘贴，自动验证、排队并下载；手动输入可按回车。不会监听整个系统剪贴板。重复粘贴不会重复创建任务。

“我的视频”自动导入原保存目录，显示缩略图、时长、大小与完成时间；支持搜索、排序、内置播放和明确区分的记录/文件删除。底部可以打开或修改后续保存目录，旧视频保持原位置。

登录、浏览器账号扫描、登录来源、更新偏好与日志在右上角设置内。浏览器信息受加密保护时会显示真实状态，可使用程序内网页登录。不同站点账号不会混用，登录值不写进日志或视频记录。

## 更新

启动后台读取实际 GitHub Releases。无更新不打扰；发现新版可暂不更新，或者进入“软件更新”查看真实说明与下载进度。支持四连接、可靠范围续传、有限重试、取消和 SHA-256 校验；未知大小使用不确定进度。

点击安装并确认后，独立助手备份原程序与设置，退出旧程序、执行安装并验证新版启动；失败时恢复。视频与网页登录资料保留。网络不可用不影响下载页，可重试或打开官方 Releases，不使用未知第三方加速源。

## 源码、构建与验证

- [桌面使用和构建说明](bilibili/README.md)
- [v2 修改清单、20 条验收与实际边界](bilibili/V2_DELIVERY.md)
- [Android 构建说明](android/README.md)
- [第三方组件许可](bilibili/packaging/THIRD_PARTY.txt)

桌面推荐标准 CPython 3.12 x64，安装 bilibili/requirements.txt、PyInstaller，准备 FFmpeg 与 Inno Setup 6 后执行 bilibili/packaging/build_windows.ps1。版本与发布仓库在 bilibili/version.json。

本次真实独立 EXE 下载样例：4 分 55 秒、1080p AV1＋AAC，从粘贴到入库并解码播放约 27 秒；已实际验证 v1.0.4 副本覆盖安装、重新启动与数据保留。82 项单元/HTTP 检查及 Qt 交互检查分别记录，不以模拟数据冒充真实下载。Windows 10 实机、双屏热切换和长期大规模媒体库压力测试尚未覆盖。

