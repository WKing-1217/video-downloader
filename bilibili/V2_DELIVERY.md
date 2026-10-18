# Windows v2.0.0 交付与验证

这是在现有下载内核上完成的 Qt Widgets 桌面重构。Windows 升级到 2.0.0；Android 保持 1.0.4。本次测试全部使用隔离数据目录、受控 HTTP Release 服务或独立的 v1.0.4 程序副本，没有用正式 GitHub 发布资源制造测试版本。

## 安装与使用

安装文件：项目根目录 `release/VideoDownloader-Windows-Setup.exe`。运行后选择原安装目录即可升级，无需卸载。源码运行使用 `bilibili/.venv/Scripts/pythonw.exe bilibili/app.py`；开发环境使用标准 CPython 3.12、完整 PySide6 及 FFmpeg。

打开后进入下载页，主动粘贴视频链接或分享文字即自动下载。手动输入可按回车提交。不会监听系统剪贴板。下载完成后到“我的视频”点击卡片播放；右键区分“删除记录”和“删除本地文件”，后者要求确认。

设置在右上角齿轮内，保留浏览器登录扫描、网页登录、登录来源、更新开关和诊断日志。更改保存目录仅影响后续任务，旧目录继续纳入视频库。

更新页读取实际配置的 `WKing-1217/video-downloader`。启动后台检查无新版时不弹窗；发现新版时可以暂不更新，或者进入第三页下载。下载通过校验后，点击“安装并重启”并确认，独立助手备份、安装并验证新版启动；失败时恢复旧版。

用户数据在 `%LOCALAPPDATA%/LocalVideoDownloader`：`settings.json`、`library.sqlite3`、`WebProfile`、缩略图缓存及更新状态。视频保存在原来选择的目录，不放进安装目录。数据库迁移前备份，较新 schema 会被拒绝而保留原文件。

## 修改文件

| 范围 | 主要文件与目的 |
| --- | --- |
| 三页 Qt 界面 | `app.py`、`ui_theme.py`、`ui_widgets.py`、`assets/nav-*.svg`、`assets/settings.svg`；共享颜色、字号、间距，保留次级设置 |
| 异步任务 | `download_service.py`、`async_jobs.py`；主动粘贴、去重、队列、取消、入库与实际进度 |
| 视频库 | `media_library.py`、`library_page.py`；SQLite、历史扫描、移动与缺失检测、虚拟化卡片、异步缩略图与缓存 |
| 本地播放 | `media_player.py`；Qt Multimedia 与随包 FFmpeg 解码，软件渲染视频帧，外部播放器备用入口 |
| 更新 | `updater.py`、`update_core.py`、`update_transfer.py`、`update_agent.py`；真实 Releases、四连接与安全续传、校验、独立安装、恢复和启动确认 |
| 下载兼容 | `downloader.py`、`douyin_gallery.py`、`platform_links.py`、`runtime_paths.py`；临时目录、成品检查、链接验证与原设置兼容 |
| 构建发布 | `version.json`、`requirements.txt`、`packaging/VideoDownloader.spec`、`installer.iss`、构建与发布脚本；独立 GUI、工作进程及更新助手 |
| Android 版本兼容 | `android/CMakeLists.txt`、`android/prepare_assets.py`；两端分别读取版本，不把旧 APK 标为 Windows 2.0 |
| 验证 | `test_v2_library.py`、`test_v2_updates.py`、`test_update_agent.py`、`qa/`、`desktop_verify.py`、更新后的 `smoke_test.py --ui` |

## 需求验收

| # | 场景 | 验证证据 |
| --- | --- | --- |
| 1 | 启动默认首页、三个导航 | Qt 交互检查及独立 EXE 检查 |
| 2 | 主动粘贴合法链接自动下载 | Ctrl+V、右键粘贴、真实 B 站独立 EXE 下载 |
| 3 | 无效链接不启动任务 | Qt 实际键盘事件 |
| 4 | 重复粘贴去重 | 两次 Ctrl+V 仅一个待处理任务键 |
| 5 | 下载期间 UI 响应 | Qt 10ms 心跳持续运行 |
| 6 | 下载后自动入库 | 完整校验后写入库，生成真实缩略图 |
| 7 | 历史文件导入预览 | 目录扫描及真实 v1.0.4 隔离升级 |
| 8 | 播放器控制与解码 | H.264 控制测试、真实 1080p AV1 出帧、缺失文件错误反馈 |
| 9 | 打开目录与修改目录 | Qt 原生目录 URL；旧根目录与文件保留 |
| 10 | 启动后台检查更新 | 本地真实 HTTP Release 服务及 Qt 定时器 |
| 11 | 已是最新不弹窗 | Qt 自动检查后仍在首页 |
| 12 | 新版提醒显示 | 实际返回的版本与 Release Notes |
| 13 | 暂不更新保持软件运行 | 点击提醒按钮，主窗口保持可见 |
| 14 | 立即更新进入第三页 | 点击提醒按钮后执行真实 HTTP 下载 |
| 15 | 字节、速度、百分比、ETA | 实际收到的字节；无总长时不确定进度 |
| 16 | 异常与取消可重试 | HTTP 503、SHA 不匹配、取消后的 Qt 重试 |
| 17 | 校验与安装失败恢复 | 原包未被损坏包替换；真实新程序启动失败后还原旧版；安装失败、路径与长文件名检查 |
| 18 | 仓库与 Releases 地址 | 从 `version.json` 读取实际仓库，页面按钮与 API 检查 |
| 19 | 升级后保留用户数据 | 独立 Inno 安装器＋冻结更新助手，视频 SHA、设置、登录资料标记及历史导入检查 |
| 20 | 独立 Windows EXE | 清除 Python/FFmpeg PATH 后实际下载、入库和播放；GUI 与助手的 PE 子系统为 Windows GUI |

自动检查：32 项原下载检查，另有 50 项单元/HTTP 检查（11 并发下载、10 旧更新兼容、8 视频库、12 新更新传输、9 安装恢复），累计 82 项。另执行 20 项 Qt 下载/库交互、16 项 Qt 更新交互、播放器控制、100%/150%/200% 离屏布局、真实联网下载及实际安装验收。受控工作进程测试与真实网站测试分别记录，没有将模拟字节称为实际网站下载。

真实 B 站 `BV1yUFPzKEC7`：294.785 秒，1920×1080，AV1＋AAC（169357 bps），38298986 字节。独立 EXE 在没有 Python/FFmpeg PATH 的环境，从粘贴到完整入库并解码播放约 27 秒。这是本机单次测量，包含解析、下载、合并、检查、入库和开始播放。

真实抖音生日短链接 `23O-7ujOLcw`：3 张图片、1 段 1.879 秒实况、284.64 秒配乐，5 个素材逐个全片解码通过，合计 5812117 字节。

该 B 站成品另经 FFmpeg 完整音画解码，返回 0 且没有错误输出。还使用真实官方 v1.0.4 GitHub Release 安装包执行四路 Range 读取，共 4 MiB、3.55 秒，验证系统代理和官方 CDN 重定向；这不是完整在线更新安装测试，也不代表固定带宽。

隔离升级：原 v1.0.4 程序副本通过实际 Inno 安装程序与独立冻结助手升级到 2.0.0，自动启动确认版本、首页、保存目录和历史数量；视频 SHA、完整设置及登录资料标记保持一致。测试发现的旧运行库冲突已修复；其失败路径也实际触发并验证了原程序恢复。

可复现检查：

```powershell
python bilibili/smoke_test.py
python -m unittest discover -s bilibili -p 'test*.py' -v
python bilibili/qa/prepare_fixture.py
python bilibili/qa/functional_probe.py
python bilibili/qa/player_probe.py
python bilibili/qa/update_ui_probe.py
python bilibili/qa/visual_probe.py 1.5
python bilibili/qa/packaged_probe.py
```

安装探针需要保留 `bilibili/dist/VideoDownloader` 的 v1.0.4 基线与单独 AppId 的 QA 安装包；不应拿正式安装目录做测试。详细本机运行记录在 `bilibili/build/v2-*/report.json` 与测试日志，交付摘要在 `release/验证记录.json`。

## 实际边界

- 真实安装与界面验收在本机 Windows 11 x64 完成；没有单独的 Windows 10 实机、低配置机器或长时间大规模媒体库压力测试。
- DPI 检查为 Qt 离屏自动检查；未进行双显示器热切换及人工连续操作验收。
- 本次真实联网回归覆盖 B 站与抖音图文。X、普通抖音保留原内核并通过链接/格式/权限检查，本次没有将旧版的真实下载记录当作新版重新下载结果。
- 浏览器应用绑定加密、站点验证、账号权限及 GitHub 线路限速仍由实际环境决定；显示真实错误并保留网页登录、重试与官方 Releases 入口，不使用未知加速源。
- 更新提醒、取消、下载错误等使用受控 Release 测试；真实安装器和更新助手已在隔离目录执行。没有为了验收改写正式发布版本或删除历史发布资源。
- 升级恢复保留备份以便故障处理，会额外占用一份运行库空间；视频不会复制到更新备份。缓存和记录均在用户目录，不覆盖原视频。
