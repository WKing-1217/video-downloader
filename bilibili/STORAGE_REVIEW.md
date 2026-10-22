# Windows 2.1.1 · 下载目录、删除与侧栏

2026-10-22，用户检查后授权发布 Windows 2.1.1，并要求发布前改为长标题单向循环滚动。Android 保持 1.0.4。

双击本目录的 **预览新版UI.bat**。本轮预览在 `build/storage-preview` 使用单独设置和媒体副本，默认打开展开侧栏的视频库。运行中的原生窗口启动截图为 `build/storage-preview/interactive-start.png`。预览里选择的新保存位置会在下次启动时继续使用。

## 已实现

- 首次安装增加视频下载目录选择；升级保留已有目录和设置，不重新应用安装默认值。
- 设置第一项与视频库底部均可更改下载目录。后台复制视频、图文、配乐、回执和下载临时文件，逐个 SHA-256 校验后切换原记录，再删除一致的旧文件。空的原目录随之清理；同名文件不覆盖，其他个人文件和未参与迁移的子目录保留。
- 复制时可取消；迁移日志支持重启恢复。原文件被占用时，可在解除占用后点击设置中的“继续迁移 / 清理”。完成前暂停作品删除，避免与清理记录冲突。
- 视频库卡片悬停显示删除图标，工具栏和 Delete 键也可删除。播放器右上角可删除当前视频。图文查看器可删除整个作品或单张图片、实况、配乐。确认后释放播放器并同步清单，取消保留文件与播放。
- 展开侧栏可拖宽并记忆偏好，随窗口宽度调整。长标题边缘渐隐、从右向左单向循环，下一份从右边接续进入；短标题不动，收起后停止动画。
- 播放器和图文查看器改为独立窗口，解除与视频库的原生所属关系，支持最小化、最大化与正常前后切换。Windows 原生窗口检查 12 项通过，保留解码、全屏与删除回归。
- 设置路径改为按当前用户数据环境读取，设置写入使用合并、线程锁和原子替换，防止预览 / QA 串入正式库或丢失保存位置。

## 原作品找不到的排查

本机排查发现原媒体仍在旧下载与预览下载目录中，正式版没有登记这些路径，所以作品列表不完整。已补回真实下载索引，没有移动或删除原媒体。库扫描继续保留已有根目录；配置读取与保存已修复，预览和测试数据与正式版隔离。

本机修复前的设置和 SQLite 一致性备份保存在用户数据目录的 `repairs` 子目录，未包含在公开源码或安装包中。

## 验证

| 检查 | 结果 |
| --- | --- |
| 单元测试 | 75 项通过，含迁移、设置隔离、单图删除和预览重启后不恢复已删样例 |
| 原下载 / 链接 / 图文完整性冒烟 | 32 项通过 |
| 粘贴、下载、入库、播放、删除与迁移集成 | 23 项通过 |
| 新目录、删除与单向循环的实际 Qt 事件 | 25 项通过，覆盖循环接续与短标题静止 |
| 原更新界面与本地 HTTP 服务回归 | 16 项通过 |
| 原生布局 100% / 150% / 200% 缩放 | 每档 41 项通过，并检查实际截图 |
| 真实 Inno 首次安装与覆盖安装 | 10 项通过，独立 AppId、用户配置与注册表键 |
| 安装后的独立 EXE | 11 项通过：读取安装选择、校验迁移、解码播放、视频及单图删除、回执同步 |

安装验收清除外部 Python / FFmpeg PATH。覆盖安装后再次启动，握手读回迁移后的新目录；设置字节保持一致。GUI 测试使用副本，未测试删除真实用户媒体。Qt 存储专项为展示真实字节进度给副本复制加入短暂延迟，报告已标记；正式实现没有该延迟。

复现：

```powershell
bilibili/.venv/Scripts/python.exe -m unittest discover -s bilibili -p 'test_*.py' -q
bilibili/.venv/Scripts/python.exe bilibili/qa/storage_ui_probe.py
bilibili/.venv/Scripts/python.exe bilibili/qa/storage_install_probe.py
```

原生界面记录见 `build/storage-review/qt-*/report.json`，冻结安装验收见 `build/storage-review/install-*/report.json`。`storage_install_probe.py` 需先构建 `dist/storage-review/VideoDownloader`；所有安装行为仅在新建的 QA 目录执行，验收后清理自己的注册表键。

本轮验证 Windows 11 x64、本地磁盘上的副本。未覆盖 Windows 10 实机、网络共享盘、突然断电或海量媒体库压力；复制取消、写设置失败、文件损坏、文件占用和中断恢复已有自动化验证。

安装目录页和首次目录种子实现参考 Inno 官方的 [CreateInputDirPage](https://jrsoftware.org/ishelp/topic_isxfunc_createinputdirpage.htm)、[RegWriteStringValue](https://jrsoftware.org/ishelp/topic_isxfunc_regwritestringvalue.htm) 与 [GetEnv](https://jrsoftware.org/ishelp/topic_isxfunc_getenv.htm)。

旧播放器作为主窗口的子对话框，在 Windows 中产生原生 owner，因而保持在所属窗口前面。已用 `GetWindow(GW_OWNER)` 读回确认，并验证改后视频库可以切到播放器和图文查看器前面；记录位于 `build/native-player-review/report.json`。窗口所属关系见 [Microsoft Owned Windows](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features#owned-windows)。
