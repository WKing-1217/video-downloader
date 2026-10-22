# 视频下载器 Windows v2.1.2

原生 Qt / PySide6 桌面应用，支持 Bilibili、抖音、X。自动选择当前权限下最高可用画质与音质，完成检查后入库；保留抖音图文、实况与配乐。Android 客户端本次保持 v1.0.4。

## 安装和使用

Windows 10 / 11 x64 双击项目根目录 `release/VideoDownloader-Windows-Setup.exe`，安装到原目录即可升级。安装包内含运行环境、FFmpeg、Qt 播放和网页登录组件，无需安装 Python。

Windows v2.1.2 使用黑白简约界面和全新品牌图标。可双击同目录的“预览新版UI.bat”打开隔离的设计预览，细节见 [UI 验收记录](UI_REVIEW.md)。

本轮支持目录迁移、可调侧栏、单向循环长标题与文件删除，播放器可独立切换和最小化、最大化。检查方式与本轮记录见 [存储和删除验收](STORAGE_REVIEW.md)。

左侧默认是窄图标栏，点击顶部 Logo 展开完整侧栏，可查看导航和最近作品，顶部按钮可收起。搜索入口或 Ctrl+K 打开独立搜索浮层，不切换当前页面；底部进入可调整大小的账号设置窗口。

- **下载**：在输入框 Ctrl+V、右键粘贴或点击粘贴按钮填入链接，点击右侧黑色箭头或按回车验证并排队下载。不会监听系统剪贴板；重复链接不会重复创建任务。
- **我的视频**：自动扫描原保存目录，显示缩略图、时长、大小与完成时间。支持搜索、排序和内置播放。删除记录保留文件；删除本地文件需要确认。
- **软件更新**：后台检查真实 GitHub Releases。无新版保持安静，发现新版可暂不更新或进入第三页下载；显示真实字节、速度与剩余时间。安装前确认退出，由独立助手安装、验证启动并在失败时恢复。

左下角设置保留浏览器登录扫描、登录来源、网页登录、更新偏好与诊断日志。浏览器加密保护或文件占用时如实显示，可使用程序内网页登录。登录信息按站点隔离，不写入视频信息或日志。

首次安装可选择视频和图片的保存目录。设置第一项或视频库底部均可更改位置；原作品在后台复制、逐个校验并更新原记录，再清理旧文件和涉及的空目录。同名目标保留，取消或校验失败时原文件保留，被占用的原文件可稍后继续清理；其他个人文件不删除。默认位置为用户“视频 / 视频下载器 / video”；源码运行默认使用项目同级 video，已有设置优先，更新不会重置已选目录。

视频库卡片悬停时显示删除图标，也可选中后点击工具栏删除、按 Delete 或使用右键菜单。播放器右上角可删除当前视频；图文查看器底部可单张删除，右上角可删除整个作品。确认后删除本地文件并同步刷新，取消时保留文件。

## 数据和更新安全

`%LOCALAPPDATA%/LocalVideoDownloader` 保存设置、SQLite 视频库、WebProfile、缩略图和更新状态，安装目录仅包含程序。原 settings.json、下载路径与网页登录配置继续使用。临时下载在保存目录的 .downloads 内，完整性检查通过后才发布为成品。

媒体下载保留最多 8 连接、B 站同格式备用节点、可靠断点检查、音画分别选优及 FFmpeg 无损合并。时长或音轨不完整会报错，损坏旧成品保留到“未通过校验”。

更新从 `version.json` 的实际仓库读取正式 Release Notes，只使用官方 GitHub 地址。安装包采用最多 4 连接、经验证的范围续传、有限重试及真实进度；没有总大小时使用不确定进度。可取得时校验 SHA-256。独立助手备份程序、设置与库，在确认旧程序退出后安装；启动失败可恢复原版。视频和登录资料不放进运行库备份或清理范围。

## 开发与构建

推荐标准 CPython 3.12 x64，避免将 Anaconda 或其他工具的 Qt DLL 混进打包环境。

```powershell
python -m venv bilibili/.venv
bilibili/.venv/Scripts/python.exe -m pip install -r bilibili/requirements.txt pyinstaller
bilibili/.venv/Scripts/pythonw.exe bilibili/app.py
```

准备 FFmpeg / ffprobe 和 Inno Setup 6，再运行 `bilibili/packaging/build_windows.ps1`。独立程序在 `bilibili/dist/v2/VideoDownloader`，安装包写入对应的 `release/v版本号` 目录。版本、Android 独立版本及实际发布仓库在 `bilibili/version.json`。

测试命令、修改清单、真实下载/安装验收和未覆盖场景见 [v2 交付记录](V2_DELIVERY.md)。图形测试的受控媒体先用 `python bilibili/qa/prepare_fixture.py` 生成，不使用正式 GitHub 发布做测试。

```powershell
python bilibili/smoke_test.py
python -m unittest discover -s bilibili -p 'test*.py' -v
python bilibili/qa/functional_probe.py
python bilibili/qa/update_ui_probe.py
python bilibili/qa/player_probe.py
```

`smoke_test.py --ui` 会在隔离目录真实联网下载并检查入库；`--gallery --url 分享链接` 检查抖音图文。独立打包验收使用 `qa/packaged_probe.py`，清除外部 Python/FFmpeg PATH 后实际下载、入库和播放。

发布时先完成验收，编辑 `release/RELEASE_NOTES.md`，运行 `packaging/package_release.py` 验证两端实际版本、整理固定文件名和生成更新清单；`github_release.py publish` 创建正式版本。旧正式 Release 保留供恢复，测试不会删除它们。

## 实际验证与边界

B 站样例 BV1yUFPzKEC7 在独立 EXE 里实测：294.785 秒、1920×1080、AV1＋169 kb/s AAC、38298986 字节；本机从粘贴到入库并解码播放约 27 秒。生日图文短链接 23O-7ujOLcw 实测保存 3 张图片、1 段实况与配乐，全部逐项完整解码。

画质按源站实际提供与用户账号权限选择，标题“4K”或“无损”不代表服务器提供相应流。支持当前视频分 P、指定 X 帖子的视频序号，不自动下载整个合集，暂不支持直播。网站验证、受保护的浏览器登录数据及网络线路会影响访问；失败时保留输入、给出原因和重试/网页登录入口。

本次在 Windows 11 x64 验证，另做 100% / 150% / 200% Qt 离屏检查；Windows 10 实机、双屏热切换和长期大规模库压力测试尚未覆盖。X 与普通抖音保留原下载内核，本次真实回归范围见交付记录。

项目：[WKing-1217/video-downloader](https://github.com/WKing-1217/video-downloader)。第三方许可见 [THIRD_PARTY.txt](packaging/THIRD_PARTY.txt)。
