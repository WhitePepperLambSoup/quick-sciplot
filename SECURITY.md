# Security Policy

## 当前边界

Quick SciPlot 会执行 LLM 生成的 Python 代码。当前执行器提供：

- 独立子进程和超时限制
- Python import 白名单
- 对文件、网络和动态执行调用的静态拦截
- 输出目录限制与导出路径校验

如果构建并启用 Docker 模式，执行器还会使用无网络、只读根文件系统、非 root 用户、capability drop、CPU/内存/PID 限制。Docker 模式需要用户自行构建并维护 `backend/Dockerfile.sandbox` 镜像。

本地 process 模式不是操作系统级沙箱；Docker 模式的隔离强度依赖 Docker Desktop/Engine 配置。用户应只在本机或受信任网络中运行，不应把当前 FastAPI 服务直接暴露到公网，也不应把不可信用户的数据提交给同一个服务实例。

## API Key

- API Key 通过本地 `.env` 保存，该文件已加入 `.gitignore`。
- `/api/config` 只返回是否配置和脱敏值。
- 提交 Issue、日志或评测报告前，请确认没有包含 API Key、数据文件或生成代码中的敏感信息。

## 报告问题

发现可能导致任意文件读写、网络访问、密钥泄露或沙箱逃逸的问题时，请不要公开发布可复现细节。优先通过 GitHub Security Advisories 私下报告，并附上版本、操作系统、Python 版本和最小复现步骤。

## 计划

后续将增加 Docker 模式的跨平台验证、镜像签名/更新策略和更严格的代码审计；在此之前请把当前版本视为本地开发工具。
