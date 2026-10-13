# AI众筹创新雷达｜公开演示站

此仓库用于发布《量化工程》模块一的 Indiegogo 众筹项目监测看板。

- 看板数据来自公开可访问的 Indiegogo 项目信息。
- GitHub Actions 每2小时尝试采集一次并发布新版看板（北京时间约为 00:17、02:17……22:17）。实际启动可能受 GitHub Actions 调度影响。
- 网页每5分钟自动刷新；数据只会在新一轮采集成功并发布后更新。
- 仓库公开，网页与仓库历史均可被任何人访问。不要在此仓库加入个人信息、账号密码、访问令牌或其他秘密。
- 工作流失败时会保留上一版网页；可在 GitHub 仓库的 Actions 页面查看公开运行日志。
- 采集和指标用于教学与市场观察，不构成投资建议。

首次设置：在仓库 Settings → Pages → Build and deployment 中，将 Source 选为 **GitHub Actions**。之后可从 Actions 页面手动运行 `Update radar data and publish site`，或等待定时任务。
