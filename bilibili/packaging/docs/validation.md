# Windows 2.1.5 发布验收

2026-11-09，用户检查 Instagram 与 YouTube 的实际导出和本地候选程序后授权发布。Android 保持 1.0.5，未新增这两个平台。

- 138 项单元检查、32 项冒烟检查通过，覆盖链接、去重、站点 Cookie 隔离、JS 运行环境、缺少时长、无音轨、解码失败与原功能。
- 用户的 Instagram Reel Deq-gX4SBrF 与 YouTube Shorts dsbT_StiFFU 已经通过真实 Qt 队列、工作进程、网络下载、MP4 导出和视频库入库；完整解码与实际取帧通过。
- Instagram：1080×1920，40.1 秒，H.264，公开响应无音轨；YouTube：1080×1920，约 28.64 秒，AV1 + AAC。没有伪造音轨或以本地素材代替网络结果。
- 冻结工作进程在仅有包内工具与 Windows 系统目录的 PATH 环境中再次联网导出成功，未借用外部 Node/Python/FFmpeg。
- 包含 Node 24.19.0（官网摘要核对）与匹配的 EJS，随附许可证。
- 正式构建再次联网下载两条用户链接并完整解码通过；16 项真实 Qt 更新流程检查通过。
- 独立 AppId 安装器和冻结更新助手成功将 2.1.4 副本升级至 2.1.5，新版自动重启，目录、视频字节、设置、登录资料和历史记录保留。发布后另外读回公开资产摘要、版本清单及应用更新检测。

功能细节与实测边界见 `bilibili/SOCIAL_REVIEW.md`。此前 MP3、存储、删除与播放器记录分别见 EXPORT_REVIEW.md、STORAGE_REVIEW.md。测试只使用隔离数据，未覆盖 Windows 10 实机、ARM Android 实机、平台登录后音轨恢复及长期网络变化。
