# 视频下载器 Android 1.0.6 / Qt Quick

安装 `release/VideoDownloader-Android.apk`，支持 Android 10 及以上的 ARM64 手机，并包含 x86_64 运行库。主界面由 Qt 6.11 / Qt Quick 构建，使用同一套 Bilibili、抖音、X、Instagram、YouTube 下载核心。无需在手机另装 Python、Qt 或 FFmpeg。

打开应用后粘贴链接或分享文字，也可以从其他应用的分享菜单选择“视频下载器”。平台自动识别；需要权限时点“网页登录”，使用软件自己的网页登录。Android 不提供读取其他浏览器账号的能力。下载由前台服务执行，显示系统通知；可以取消。

1.0.6 沿用蓝灰配色、白色输入区和黑白线条图形，底部提供“下载 / 提取 MP3 / 作品 / 设置”四个等宽入口。下载与提取分别保留输入、错误、进度和完成结果，支持继续添加任务排队；切换页面不会把另一任务的反馈覆盖掉。顶部与底部避让系统栏和软键盘，从系统播放器返回时恢复正常布局。

“提取 MP3”支持作品链接，也可以通过系统文件选择器选择已有 MP4 等视频。选中的文件只读，程序在私有工作区提取，保留原视频；下载完成的视频也提供提取 MP3 入口。取消文件选择不会启动任务。取消提取会等待工作进程退出后恢复操作，避免旧任务的退出覆盖新任务。

设置中可选视频 MP4（默认）/ MKV / MOV / WebM，图片 PNG（默认）/ JPEG / WebP，MP3 128 / 192（默认）/ 256 / 320 kbps；选择会保留到下次启动。结果经过类型、音轨与完整时长检查后，保存到系统“下载 / 视频下载器”。图文按作品分文件夹保留图片、实况片段和 MP3 配乐。只导出媒体文件，不生成视频或图文 JSON 附件；内部状态记录保留在应用私有目录。

完成后可以查看或分享文件，MP3 使用音频 MIME 类型打开。系统下载目录使用待完成条目保存，整组复制成功后才提交，失败或取消时清理本次待完成条目。同名文件另存；卸载后系统下载目录中的结果仍保留。

## 构建

本次使用 Qt 6.11.1（android_arm64_v8a、android_x86_64 和 Windows 主机工具）、JDK 21、Android SDK 36 / Build Tools 36.0.0、NDK 27.2.12479018、Gradle 9.3.1 与 AGP 9.0.0。`prepare_assets.py` 生成共享 Python 代码和 yt-dlp 归档；`prepare_runtime.py` 获取并校验固定版本的 FFmpeg AAR。

1. 在项目 Python 环境运行 `prepare_runtime.py` 和 `prepare_assets.py`。
2. 使用 `android_arm64_v8a/bin/qt-cmake.bat` 配置 CMake，设置 Android SDK、NDK、主机 Qt 路径及 `QT_ANDROID_ABIS=arm64-v8a;x86_64`。
3. CMake `apk` 目标构建两套 Qt 原生库并生成 Gradle 项目。
4. 在生成的 `android-build` 目录运行 `gradlew.bat assembleRelease`。配置 `VIDEO_DOWNLOADER_SIGNING` 指向本机签名属性文件，属性包含 `storeFile`、`storePassword`、`keyAlias`、`keyPassword`；私钥和密码不进入源码发行包。
5. 发布 `android-build/build/outputs/apk/release/android-build-release.apk`，并运行 Android SDK 的 `apksigner verify` 检查。

Gradle 自行签名后规范产物为 `android-build-release.apk`。构建脚本另创建一个完全相同的文件名别名，供 Qt 的默认复制步骤使用；两个文件实际都已签名。发布前仍须运行 `apksigner verify`，不以旧 APK 的存在作为构建成功依据。

QtQuick / C++ 界面通过 `DownloadBridge` 与 Java 前台服务通信；Python 和 FFmpeg 由固定版本 `youtubedl-android` 运行库提供。后台使用应用原生库目录的可执行文件，账号信息通过标准输入传给下载进程。资源包只包含程序代码、公共下载引擎和 CA 根证书，不包含本机账号。

Android 运行库的 Python 不提供 `os.link`；`android_bootstrap.py` 仅为 Android 替换私有文件发布步骤，使用排他创建和完整复制防止同名覆盖。公共导出仍在 MediaStore `IS_PENDING` 中完成。工作区使用应用内部目录，不依赖模拟外部存储的硬链接能力。

## 1.0.5 验证范围

- 双 ABI 的签名 APK 构建成功，版本名 1.0.5、版本代码 105；签名证书与原 1.0.4 一致，可覆盖升级。
- x86_64 Android 模拟器上实际通过系统文件选择器选取“测试+已有视频.mp4”，完整经过前台服务、内置 Python/FFmpeg 和 MediaStore 保存为 MP3，原文件 SHA-256 不变；媒体条目为 `audio/mpeg` 且不再待完成。
- 模拟器原生 FFmpeg 实测 PNG/JPEG/WebP、MP4/MKV/MOV/WebM 和四档 MP3，共 11 个转换变体，全解码校验通过，输出中无 JSON 附件。
- 格式设置重启保留、文件选择取消、正在执行的 MP3 提取取消及恢复操作已验证。实际 Android 截图位于 `build-1.0.5/`，验收记录为 `build-1.0.5/acceptance.json`。
- ARM64 已完成构建与打包，尚未在实体 ARM64 手机验证。Bilibili、抖音和 X 的本次真实在线 MP3 下载未实测；不能把受控媒体转换验证当作网站在线验收。

参考：
- https://doc.qt.io/qt-6.11/android.html
- https://doc.qt.io/qt-6.11/android-building-projects-from-commandline.html
- https://github.com/yausername/youtubedl-android

`preview_qml.py` 可在桌面渲染手机尺寸的真实 QML，用于检查布局；它使用展示状态，不代表安卓设备上的实际下载测试。


## 自动检查更新

1.0.2 启动时从 GitHub 检查更新，也可点击“检查更新”。发现新版后打开 GitHub APK 链接，由 Android 系统确认安装。更多选项中可关闭启动检查。版本号、版本代码及仓库统一来自 bilibili/version.json。

## 1.0.6 更新

本轮针对真实手机截图修正状态栏重叠、底部入口宽度与图标语义，保留蓝灰主题。顶部、正文与底部显式分区，由一层负责系统安全区域，避免重复内边距。设置图标为齿轮，四个等宽导航分别对应下载、提取 MP3、作品、设置；输入和任务状态分别保留。

手机端补齐 Instagram 与 YouTube / Shorts，使用共享链接解析与导出内核。APK 使用原有 Android 运行库中的 QuickJS（libqjs.so）和匹配的 EJS 脚本，不依赖 Windows Node。抖音实况以独立 MP4 保存，与静态图片、配乐共同展示；不是把静态封面伪装为动画。

作品库保留本应用实际保存的公共媒体 URI，支持搜索、打开、分享、整组删除、单文件删除和从视频提取 MP3。删除先确认，只删除明确记录的 URI。旧版最后一次结果和本应用拥有的下载条目会导入，不申请读取全部存储权限。

保存位置可使用系统文件夹选择器，更改后后台复制已有作品、逐个 SHA-256 校验，再持久化新 URI 和目录，最后删除原文件。迁移日志用于中断恢复；同名文件另存，源文件发生变化时保留原文件。未能清理时保留日志，阻止新下载覆盖恢复记录。Android 系统不允许的文件夹不会强行绕过权限。

Android 原生实测已完成 Instagram、YouTube 和抖音实况导出，保存后的文件逐项校验并完整解码。146项发布源码检查通过，另有真实QML、队列、删除、迁移、冷启动和播放器返回检查。具体范围见 [Android验收记录](UI_PARITY_REVIEW.md)。本次 Windows 安装包继续提供 v2.1.5。
