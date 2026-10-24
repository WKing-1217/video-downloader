# MP3 与导出格式本地验收

日期：2026-10-23。本轮 Windows v2.1.4 已获上线授权；本文件记录开发及本地验收，正式成品和公开发布验收另见 release/VALIDATION-v2.1.4.json。

## 功能

- 左侧新增“提取 MP3”独立页面：粘贴链接并提交，或选择本地视频提取。首页恢复原来的问候、链接输入与最近三个作品，不再放保存类型下拉框或本地提取按钮。
- 下载页与提取页复用相同的输入框、粘贴/提交按钮、进度和反馈组件，沿用蓝灰色设计系统、留白、字重与线条图标；两页独立保留输入、错误与任务状态，切换页面不会丢失。
- 视频库工具栏、右键菜单、播放窗口均提供 MP3 提取，并进入独立提取页查看进度和结果。MP3 可在视频库中管理和删除，打开时调用 Windows 默认播放器；图文配乐也使用默认播放器。
- 视频 MP4（默认）/ MKV / MOV / WebM；图片 PNG（默认）/ JPEG / WebP；MP3 128 / 192（默认）/ 256 / 320 kbps。
- 设置即时保存，每个排队任务保留提交时的格式与音质；视频和音频分别查重，旧 JPG 图文不会挡住新 PNG 导出。
- 导出不写 JSON 附件。作品信息保存在程序的数据目录；旧 JSON 兼容读取，不主动清理历史文件。
- 本地视频只读、同名自动另存；转换完整校验后发布。AV1 导出 MP4 可直接封装。图文整组暂存后发布，失败不暴露半成品。
- 媒体库可在没有 JSON 的情况下重新发现图文、识别音频和独立图片，并继续删除及迁移。

## 已执行验证

本轮独立提取页验收：

- 27 项 MP3 界面与真实 FFmpeg 流程检查通过，覆盖独立导航、两页输入/错误/进度互不串页、链接模式、真实本地选择器提取、入库与原文件哈希保护。
- 26 项原界面流程检查通过；100% 与 150% Qt 比例各 47 项界面回归检查通过。
- 已实际查看默认 1120×780、最小 860×620、宽屏 1440×900、展开侧栏、提取完成、回到首页及设置截图；未见控件裁切或风格漂移。预览入口直接进入独立提取页。

此前 MP3 内核与格式功能验证继续保留：

在项目 `.venv`、Windows 11、真实 FFmpeg 与 Qt 控件执行：

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -p 'test*.py' -q
.venv/Scripts/python.exe -X utf8 smoke_test.py
.venv/Scripts/python.exe -X utf8 qa/functional_probe.py
.venv/Scripts/python.exe -X utf8 qa/export_probe.py
.venv/Scripts/python.exe -X utf8 preview_ui.py --capture --scale 1 --work-dir build/export-visual-regression
.venv/Scripts/python.exe -X utf8 preview_ui.py --capture --scale 1.5 --work-dir build/export-visual-regression-150
```

- 单元测试累计 120 项通过（全量 118 项及新增 2 项重试定向回归）；队列与页面路由的定向检查合跑 19 项通过，内核冒烟检查 32 项通过。覆盖真实格式转换、全解码、MP3 各码率、无音轨、同名保护、受损缓存、无 JSON 图文分组、删除、目录迁移及两页任务隔离。
- 此前 23 项原界面流程检查、41 项界面回归检查及 12 项 MP3 流程检查已通过；本轮独立页面检查已按上方数量重新执行并扩充。
- 补测发现本机 Qt FFmpeg 音频路径在初载快速暂停、定位后关闭时会阻塞；自然结束也曾在嵌套自动化事件循环中阻塞，不能据此认定正常窗口播放至结尾必然出错。最终版本的 MP3 和图文配乐通过默认播放器打开，程序不使用该音频播放路径；原视频播放器与导出入口继续保留。

## 在线边界

公开 Bilibili 链接 `BV1yUFPzKEC7` 使用 `--mode audio --no-browser-cookies` 实测时，站点在网页解析阶段返回 HTTP 412，未进入媒体下载。该次没有生成媒体或 JSON，不能视为在线 MP3 下载验收通过。链接模式已用受控解析器、真实 FFmpeg 验证其选择音轨与导出流程；抖音、X 的真实在线 MP3 尚未实测。

## 预览和截图

双击 `预览MP3与格式.bat`，或运行：

```powershell
.venv/Scripts/pythonw.exe preview_ui.py --work-dir build/mp3-preview --page 3 --snapshot-on-start
```

预览的设置与示例文件独立于正式数据。交互式链接下载与 MP3 提取是真实操作。`--mode audio` 继续兼容，但现在进入第 3 页，不再改变首页模式。实际控件截图在 `build/export-review/`（首页、独立提取页、展开侧栏、宽/窄窗口、格式设置、视频库、MP3 完成及视频播放器）；常规界面回归截图在 `build/export-visual-regression/`。
