import { useEffect, useRef } from "react";
import type { LLMConfig } from "../types";
import type { Language } from "./ParameterInput";

export type BackendState = "connecting" | "ready" | "failed";

interface HeaderProps {
  language: Language;
  llmConfig: LLMConfig;
  backendState: BackendState;
  sandboxReady: boolean | null;
  busy: boolean;
  hasDataset: boolean;
  canBatch: boolean;
  onToggleLanguage: () => void;
  onOpenSettings: () => void;
  onOpenSetup: () => void;
  onUploadFiles: (files: File[]) => void;
  onOpenMimic?: () => void;
  onOpenComposer?: () => void;
  onOpenTemplates?: () => void;
  onOpenBatch?: () => void;
}

export function Header({
  language,
  llmConfig,
  backendState,
  sandboxReady,
  busy,
  hasDataset,
  canBatch,
  onToggleLanguage,
  onOpenSettings,
  onOpenSetup,
  onUploadFiles,
  onOpenMimic,
  onOpenComposer,
  onOpenTemplates,
  onOpenBatch,
}: HeaderProps) {
  const zh = language === "zh";
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o" && !busy) {
        event.preventDefault();
        fileRef.current?.click();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [busy]);

  let statusClass = "";
  let statusText: string;
  if (backendState === "connecting") {
    statusClass = "connecting";
    statusText = zh ? "正在启动本地服务…" : "Starting local service…";
  } else if (backendState === "failed") {
    statusClass = "failed";
    statusText = zh ? "无法连接本地服务" : "Local service unavailable";
  } else if (llmConfig.mock) {
    statusClass = "mock";
    statusText = zh ? "Mock 模式" : "Mock Mode";
  } else if (llmConfig.has_api_key || llmConfig.allow_loopback_llm) {
    statusClass = "ready";
    statusText = `${zh ? "已连接" : "Ready"} · ${llmConfig.model}`;
  } else {
    statusText = zh ? "未配置模型" : "No model configured";
  }

  return (
    <header className="header">
      <div className="brand-wrapper">
        <div className="brand-icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3v18h18" />
            <path d="M18 9l-5 5-4-4-6 6" />
          </svg>
        </div>
        <h1>
          Quick SciPlot
          <span className="header-badge">v{__APP_VERSION__}</span>
        </h1>
      </div>

      <span className="sub">{zh ? "出版级科研数据可视化工作台 · LLM 智能驱动" : "Publication-Grade Scientific Plotting Workbench · LLM-Powered"}</span>

      <div className="header-tools">
        <div className={`llm-status ${statusClass}`} title={statusText}>
          <span className="status-dot" />
          <span>{statusText}</span>
        </div>

        {backendState === "ready" && sandboxReady !== null && (
          <button
            className={`btn small ${sandboxReady ? "ghost" : "warning"}`}
            onClick={onOpenSetup}
            title={zh ? "代码执行环境与首次使用设置" : "Execution environment and setup"}
          >
            <span>{sandboxReady ? "🛡️" : "⚠️"}</span>
            <span>{sandboxReady ? (zh ? "环境就绪" : "Ready") : zh ? "完成设置" : "Finish setup"}</span>
          </button>
        )}

        {hasDataset && onOpenTemplates && (
          <button className="btn secondary" onClick={onOpenTemplates} disabled={busy} title={zh ? "火山图、生存曲线、PCA 等常用科研图" : "Volcano, survival, PCA and more"}>
            <span>🧪</span>
            <span>{zh ? "模板" : "Templates"}</span>
          </button>
        )}

        {hasDataset && onOpenMimic && (
          <button className="btn secondary" onClick={onOpenMimic} disabled={busy} title={zh ? "上传论文图照片或选择模板进行版式复刻" : "Mimic a paper figure"}>
            <span>🎨</span>
            <span>{zh ? "论文图复刻" : "Mimic"}</span>
          </button>
        )}

        {hasDataset && onOpenComposer && (
          <button className="btn secondary" onClick={onOpenComposer} disabled={busy} title={zh ? "将多个子图拼版为组合大图" : "Compose multi-panel figures"}>
            <span>📊</span>
            <span>{zh ? "多图拼版" : "Composer"}</span>
          </button>
        )}

        {canBatch && onOpenBatch && (
          <button className="btn secondary" onClick={onOpenBatch} disabled={busy} title={zh ? "把当前代码套用到多个数据集" : "Apply the current code to several datasets"}>
            <span>🗃️</span>
            <span>{zh ? "批量" : "Batch"}</span>
          </button>
        )}

        <button className="btn secondary" onClick={onToggleLanguage} disabled={busy} title="切换中英文 / Switch Language">
          <span>🌐</span>
          <span>{zh ? "EN" : "中文"}</span>
        </button>

        <button className="btn secondary" onClick={onOpenSettings} disabled={busy} title={zh ? "配置模型与执行环境" : "Model and execution settings"}>
          <span>⚙️</span>
          <span>{zh ? "设置" : "Settings"}</span>
        </button>

        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
          hidden
          onChange={(e) => {
            onUploadFiles(Array.from(e.target.files || []));
            e.currentTarget.value = "";
          }}
        />

        <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy} title={zh ? "也可以把文件拖进窗口（Ctrl+O）" : "Or drop files onto the window (Ctrl+O)"}>
          <span>📁</span>
          <span>{zh ? "导入数据" : "Import Data"}</span>
        </button>
      </div>
    </header>
  );
}
