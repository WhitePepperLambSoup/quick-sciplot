import { useEffect, useState } from "react";
import { getSystemStatus, setSandboxMode, startDockerImageBuild } from "../api";
import type { SystemStatus } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface SetupWizardProps {
  language: Language;
  status: SystemStatus;
  onStatusChange: (status: SystemStatus) => void;
  onOpenSettings: () => void;
  onEnableMock: () => Promise<void>;
  onClose: () => void;
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={`setup-check ${ok ? "ok" : "missing"}`}>
      <span className="setup-check-icon">{ok ? "✓" : "✕"}</span>
      <span>{label}</span>
    </div>
  );
}

export function SetupWizard({ language, status, onStatusChange, onOpenSettings, onEnableMock, onClose }: SetupWizardProps) {
  const zh = language === "zh";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  useEscape(onClose, !busy);

  const building = status.image_build.state === "running";

  useEffect(() => {
    if (!building) return;
    const timer = window.setInterval(() => {
      getSystemStatus().then(onStatusChange).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [building, onStatusChange]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const refresh = () => run(async () => onStatusChange(await getSystemStatus()));
  const docker = status.docker;
  const dockerReady = docker.daemon_running && docker.image_present;

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-dialog setup-wizard" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? "🧭 开始使用 Quick SciPlot" : "🧭 Get started with Quick SciPlot"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="modal-body">
          <div className={`setup-banner ${status.sandbox_ready ? "ready" : "blocked"}`}>
            {status.sandbox_ready
              ? zh
                ? `✓ 绘图执行环境已就绪（${status.sandbox_mode === "docker" ? "Docker 沙箱" : "本地 worker"}）`
                : `✓ Plot execution is ready (${status.sandbox_mode === "docker" ? "Docker sandbox" : "local worker"})`
              : zh
              ? "⚠️ 还不能出图：请先选择一种代码执行方式"
              : "⚠️ Plots cannot run yet: choose how generated code is executed"}
          </div>

          <h4 className="setup-section-title">{zh ? "1. 代码执行方式" : "1. Code execution"}</h4>
          <div className="setup-options">
            <section className={`setup-card ${status.sandbox_mode === "docker" ? "current" : ""}`}>
              <div className="setup-card-title">
                <strong>{zh ? "Docker 沙箱（推荐）" : "Docker sandbox (recommended)"}</strong>
                {status.sandbox_mode === "docker" && <span className="setup-tag">{zh ? "当前" : "Current"}</span>}
              </div>
              <p className="modal-desc">
                {zh
                  ? "生成的代码在无网络、只读、非 root 的容器中运行，安全性最高。"
                  : "Generated code runs in a container without network, read-only and non-root."}
              </p>
              <Check ok={docker.installed} label={zh ? "已安装 Docker Desktop" : "Docker Desktop installed"} />
              <Check ok={docker.daemon_running} label={zh ? "Docker 正在运行" : "Docker is running"} />
              <Check ok={docker.image_present} label={zh ? `沙箱镜像 ${docker.image}` : `Sandbox image ${docker.image}`} />
              {!docker.installed && (
                <p className="setup-hint">
                  {zh ? "请先从 docker.com 下载安装 Docker Desktop，启动后点击“刷新状态”。" : "Install Docker Desktop from docker.com, start it, then click Refresh."}
                </p>
              )}
              {docker.installed && !docker.daemon_running && (
                <p className="setup-hint">{zh ? "请先启动 Docker Desktop，然后点击“刷新状态”。" : "Start Docker Desktop, then click Refresh."}</p>
              )}
              <div className="setup-actions">
                {docker.daemon_running && !docker.image_present && status.can_build_image && (
                  <button className="btn small" disabled={busy || building} onClick={() => run(async () => {
                    await startDockerImageBuild();
                    onStatusChange(await getSystemStatus());
                  })}>
                    {building ? (zh ? "镜像构建中…" : "Building…") : zh ? "构建沙箱镜像" : "Build sandbox image"}
                  </button>
                )}
                {status.sandbox_mode !== "docker" && dockerReady && (
                  <button className="btn secondary small" disabled={busy} onClick={() => run(async () => onStatusChange(await setSandboxMode("docker")))}>
                    {zh ? "改用 Docker 沙箱" : "Use Docker sandbox"}
                  </button>
                )}
              </div>
              {(building || status.image_build.state === "failed" || status.image_build.state === "succeeded") && (
                <div className="setup-build">
                  <div className={`setup-build-state ${status.image_build.state}`}>
                    {status.image_build.state === "running" && (zh ? "正在构建，首次需要下载约 1 GB，可能需要几分钟…" : "Building; the first build downloads about 1 GB…")}
                    {status.image_build.state === "succeeded" && (zh ? "✓ 镜像构建完成" : "✓ Image built")}
                    {status.image_build.state === "failed" && `✕ ${status.image_build.error}`}
                  </div>
                  {status.image_build.log.length > 0 && <pre className="setup-log">{status.image_build.log.slice(-12).join("\n")}</pre>}
                </div>
              )}
              {dockerReady && status.sandbox_mode === "docker" && <p className="setup-ok">{zh ? "✓ Docker 沙箱可以使用" : "✓ Docker sandbox ready"}</p>}
            </section>

            <section className={`setup-card ${status.sandbox_mode === "process" ? "current" : ""}`}>
              <div className="setup-card-title">
                <strong>{zh ? "本地 worker（无需 Docker）" : "Local worker (no Docker)"}</strong>
                {status.sandbox_mode === "process" && <span className="setup-tag">{zh ? "当前" : "Current"}</span>}
              </div>
              <p className="modal-desc">
                {zh
                  ? "在本机独立进程中运行代码，有静态检查、超时和输出限额，但不是操作系统级沙箱。只适合运行你信任的代码与模型。"
                  : "Runs code in a separate local process with static checks, timeouts and output limits, but it is not an OS-level sandbox. Use it only with code and models you trust."}
              </p>
              {status.sandbox_mode === "process" && status.process_allowed ? (
                <p className="setup-ok">{zh ? "✓ 已启用本地 worker" : "✓ Local worker enabled"}</p>
              ) : status.can_enable_process ? (
                (
                  <>
                    <label className="settings-check setup-consent">
                      <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                      <span>{zh ? "我了解本地 worker 不是安全沙箱，仍要启用" : "I understand the local worker is not a security sandbox"}</span>
                    </label>
                    <div className="setup-actions">
                      <button className="btn small" disabled={busy || !acknowledged} onClick={() => run(async () => onStatusChange(await setSandboxMode("process", true)))}>
                        {zh ? "启用本地 worker" : "Enable local worker"}
                      </button>
                    </div>
                  </>
                )
              ) : (
                <p className="setup-hint">
                  {zh
                    ? "浏览器开发模式下请在 backend/.env 中设置 SANDBOX_MODE=process 和 ALLOW_UNSAFE_PROCESS_SANDBOX=1 后重启后端。"
                    : "In browser development mode set SANDBOX_MODE=process and ALLOW_UNSAFE_PROCESS_SANDBOX=1 in backend/.env and restart the backend."}
                </p>
              )}
            </section>
          </div>

          <h4 className="setup-section-title">{zh ? "2. AI 模型" : "2. AI model"}</h4>
          <div className="setup-model-row">
            <Check
              ok={status.llm_configured}
              label={
                status.llm_mock
                  ? zh ? "Mock 演示模式（不调用真实模型）" : "Mock mode (no real model)"
                  : status.llm_configured
                  ? zh ? "已配置模型" : "Model configured"
                  : zh ? "尚未配置模型 API Key 或本机模型" : "No API key or local model configured"
              }
            />
            <div className="setup-actions">
              <button className="btn secondary small" disabled={busy} onClick={onOpenSettings}>
                {zh ? "配置模型（含 Ollama 本机模型）" : "Configure model (incl. local Ollama)"}
              </button>
              {!status.llm_configured && (
                <button className="btn secondary small" disabled={busy} onClick={() => run(onEnableMock)}>
                  {zh ? "先用 Mock 模式体验" : "Try mock mode"}
                </button>
              )}
            </div>
          </div>

          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={refresh} disabled={busy}>
            {zh ? "刷新状态" : "Refresh"}
          </button>
          <button className="btn" onClick={onClose} disabled={busy}>
            {status.sandbox_ready ? (zh ? "完成" : "Done") : zh ? "稍后再说" : "Later"}
          </button>
        </div>
      </div>
    </div>
  );
}
