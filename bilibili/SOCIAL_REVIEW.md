# Instagram 与 YouTube：Windows 2.1.5 验收

2026-11-09。用户提供两条链接并要求以真实导出成功为验收。功能先在隔离目录完成本地候选验收，用户检查后授权发布 Windows 2.1.5。升级与下载测试不修改真实下载目录或登录设置；Android APK 保持 1.0.5，未增加新平台。

## 实现

- 支持 Instagram 单视频 Reel/帖子、YouTube 视频/Shorts/youtu.be；移除分享追踪参数，同视频不同链接统一去重键。
- 沿用 Qt 下载队列、工作进程、进度、取消、重试、MP4 和 MP3 导出、视频库与缩略图。
- 继续只读取目标站点 Cookie，值留在内存，网页登录入口按平台隔离。不使用 Cookie 的公开访问已实测。
- Windows 包内置 Node 24.19.0 与 yt-dlp 2026.10.26、匹配的 EJS 0.8.0；Node 二进制已对照官网 SHA-256，许可证随包。Node/EJS 要求见 https://github.com/yt-dlp/yt-dlp/wiki/EJS 。
- Instagram 未提供时长时，不复用上次未知完整性的缓存；成功传输后读取源文件时长，再做导出时长核对与全量解码。
- 仅当 Instagram 明确返回无音轨格式且没有可用音轨时允许视频无声导出；完成状态说明无音轨，不伪造声音。未明确无声而下载缺音轨仍拒绝。无声媒体不能提取 MP3。

## 用户链接与实际结果

| 平台 / 视频 ID | MP4 实际成品 | 音视频 | 验证 |
| --- | --- | --- | --- |
| Instagram / Deq-gX4SBrF | 1080×1920，40.1 秒，约 50.3 MiB | H.264，公开响应没有音轨 | 完整解码、实际取帧、视频库入库 |
| YouTube / dsbT_StiFFU | 1080×1920，约 28.64 秒，约 6.8 MiB | AV1 + AAC | 完整解码、实际取帧、视频库入库 |

以上均为用户链接的实际联网导出，不是本地素材伪装成下载结果。Instagram 的公开音轨缺失不代表原帖必然无声，登录后可能不同，本轮未使用用户账号验证音轨恢复。

## 检查记录

- 138 项单元检查、32 项冒烟检查通过；新增链接校验、站点 Cookie 隔离、去重、JS 运行时选择、缺时长、无声音轨和解码失败保留文件测试。
- 真实 Qt 队列 → 源码 worker → FFmpeg → 成品 → 视频库完成；检查 UI 心跳和重复提交去重。
- 本地 review 构建位于 `dist/social-review/VideoDownloader`；正式安装路径不受影响。
- 频道/播放列表、直播、Instagram 图片与多媒体轮播不在本次范围。登录受限、地区限制与平台响应变化可能影响其他链接。本轮只验收 Windows，不代表 Android 支持这些链接。

双击 `预览INS与YouTube.bat` 打开隔离预览。可复跑 `qa/social_download_probe.py`，或增加 `--worker dist/social-review/VideoDownloader/download-worker.exe` 复测冻结 worker。冻结测试限制 PATH 为包内工具和 Windows 系统目录。

冻结 worker 联网复测也通过：`build/social-review-1794155561646241900/report.json`，两份 MP4 均全量解码、取帧及入库成功。该次仅允许包内工具与 Windows 系统目录出现在 PATH，未借用外部 Python/Node/FFmpeg。源码实测报告：`build/social-review-1794155277408780100/report.json`。

## 2.1.5 正式候选复验

2026-11-09，正式构建的下载工作进程再次成功导出两条用户链接，并通过视频库入库、重复链接去重、UI 心跳、完整解码与实际取帧。报告为 `build/social-review-1794156028856014500/report.json`。

138 项单元检查及 16 项更新流程检查通过。独立 AppId 的真实 Inno 安装器与冻结更新助手将隔离的 2.1.4 副本升级至 2.1.5，新版自动重启；原视频 SHA-256、保存目录、设置、登录资料与历史记录保留。报告为 `build/v2-upgrade-1794156036117527700/report.json`。既有 32 项内核冒烟检查通过。
