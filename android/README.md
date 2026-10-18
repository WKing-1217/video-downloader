# 视频下载器 Android / Qt Quick

安装 `release/VideoDownloader-Android.apk`，支持 Android 10 及以上的 ARM64 手机，并包含 x86_64 运行库。主界面由 Qt 6.11 / Qt Quick 构建，使用同一套 Bilibili、抖音、X 下载核心。无需在手机另装 Python、Qt 或 FFmpeg。

打开应用后粘贴链接或分享文字，也可以从其他应用的分享菜单选择“视频下载器”。平台自动识别；需要权限时点“网页登录”，使用软件自己的网页登录。Android 不提供读取其他浏览器账号的能力。下载由前台服务执行，显示系统通知；可以取消。

结果经过媒体类型、画面/声音与完整时长检查后，保存到系统“下载 / 视频下载器”。图文按作品分文件夹保留原图、实况片段与背景音乐。完成后可以查看或分享文件。取消或失败不会显示完成。私有工作目录保留下载过程文件，卸载后系统下载目录中的结果仍保留。

## 构建

本次使用 Qt 6.11.1（android_arm64_v8a、android_x86_64 和 Windows 主机工具）、JDK 21、Android SDK 36 / Build Tools 36.0.0、NDK 27.2.12479018、Gradle 9.3.1 与 AGP 9.0.0。`prepare_assets.py` 生成共享 Python 代码和 yt-dlp 归档；`prepare_runtime.py` 获取并校验固定版本的 FFmpeg AAR。

1. 在项目 Python 环境运行 `prepare_runtime.py` 和 `prepare_assets.py`。
2. 使用 `android_arm64_v8a/bin/qt-cmake.bat` 配置 CMake，设置 Android SDK、NDK、主机 Qt 路径及 `QT_ANDROID_ABIS=arm64-v8a;x86_64`。
3. CMake `apk` 目标构建两套 Qt 原生库并生成 Gradle 项目。
4. 在生成的 `android-build` 目录运行 `gradlew.bat assembleRelease`。配置 `VIDEO_DOWNLOADER_SIGNING` 指向本机签名属性文件，属性包含 `storeFile`、`storePassword`、`keyAlias`、`keyPassword`；私钥和密码不进入源码发行包。
5. 发布 `android-build/build/outputs/apk/release/android-build-release.apk`，并运行 Android SDK 的 `apksigner verify` 检查。

Gradle 自行签名后规范产物为 `android-build-release.apk`。构建脚本另创建一个完全相同的文件名别名，供 Qt 的默认复制步骤使用；两个文件实际都已签名。发布前仍须运行 `apksigner verify`，不以旧 APK 的存在作为构建成功依据。

QtQuick / C++ 界面通过 `DownloadBridge` 与 Java 前台服务通信；Python 和 FFmpeg 由固定版本 `youtubedl-android` 运行库提供。后台使用应用原生库目录的可执行文件，账号信息通过标准输入传给下载进程。资源包只包含程序代码、公共下载引擎和 CA 根证书，不包含本机账号。

参考：
- https://doc.qt.io/qt-6.11/android.html
- https://doc.qt.io/qt-6.11/android-building-projects-from-commandline.html
- https://github.com/yausername/youtubedl-android

`preview_qml.py` 可在桌面渲染手机尺寸的真实 QML，用于检查布局；它使用展示状态，不代表安卓设备上的实际下载测试。


## 自动检查更新

1.0.2 启动时从 GitHub 检查更新，也可点击“检查更新”。发现新版后打开 GitHub APK 链接，由 Android 系统确认安装。更多选项中可关闭启动检查。版本号、版本代码及仓库统一来自 bilibili/version.json。
