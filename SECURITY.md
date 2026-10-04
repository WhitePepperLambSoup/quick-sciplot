# Security Policy

## 当前边界

Quick SciPlot 会执行 LLM 生成的 Python 代码。当前执行器提供：

- 独立子进程和超时限制
- Python import 白名单
- 对文件、网络和动态执行调用的静态拦截
- 执行期间的日志、单文件产物和输出目录大小限制
- 只允许 `data_dir` 下普通 CSV 数据集，以及 `data_dir/outputs` 下的版本产物
- 上传流式写入、批量导入回滚、JSON 嵌套限制、Excel ZIP 展开限制、行/列/单元格限制
- 解析/绘图并发上限与 SQLite 历史产物配额清理
- Host 请求头白名单（`ALLOWED_HOSTS`）以防御 DNS 重绑定；桌面版通过 Tauri 命令取得会话 token，以请求头而非跨站 cookie 认证

如果构建并启用 Docker 模式，执行器还会使用无网络、只读根文件系统、非 root 用户、capability drop、CPU/内存/PID 限制。Docker 模式需要用户自行构建并维护 `backend/Dockerfile.sandbox` 镜像。

本地 process 模式不是操作系统级沙箱；Docker 模式的隔离强度依赖 Docker Desktop/Engine 配置。用户应只在本机或受信任网络中运行，不应把当前 FastAPI 服务直接暴露到公网，也不应把不可信用户的数据提交给同一个服务实例。

项目仍是本机单用户服务：SQLite 记录没有用户/租户 ACL，实例 token 不是多用户身份系统。共享部署前必须增加用户认证、对象级授权、审计和隔离；当前版本不支持把本地端口暴露给不可信用户。

## API Key

- API Key 通过本地 `.env` 保存，该文件已加入 `.gitignore`。
- `/api/config` 只返回是否配置和脱敏值。
- 提交 Issue、日志或评测报告前，请确认没有包含 API Key、数据文件或生成代码中的敏感信息。

## 报告问题

发现可能导致任意文件读写、网络访问、密钥泄露或沙箱逃逸的问题时，请不要公开发布可复现细节。优先通过 GitHub Security Advisories 私下报告，并附上版本、操作系统、Python 版本和最小复现步骤。

## 依赖与验证边界

- `backend/requirements.lock.txt` 和 `requirements-sandbox.lock.txt` 使用精确版本，但当前不包含包 hash，因此不能宣称达到 hash 级供应链完整性。
- 已提供 SBOM 生成入口，但是否生成取决于构建时的 `GENERATE_SBOM=1`。
- 每次推送由 GitHub Actions 运行后端测试、前端构建以及 Tauri 的 `cargo fmt`、`clippy` 和单元测试；Docker 镜像构建和实际容器运行尚未纳入自动化验证。
- 在 Docker 跨平台验证、镜像签名/更新策略和更严格的代码审计完成前，请把当前版本视为本地开发工具。
