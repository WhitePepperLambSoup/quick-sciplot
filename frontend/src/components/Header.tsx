import { useRef } from "react";
import type { LLMConfig } from "../types";
import type { Language } from "./ParameterInput";

interface HeaderProps {
  language: Language;
  llmConfig: LLMConfig;
  busy: boolean;
  hasDataset: boolean;
  onToggleLanguage: () => void;
  onOpenSettings: () => void;
  onUploadFiles: (files: File[]) => void;
  onOpenMimic?: () => void;
  onOpenComposer?: () => void;
}

export function Header({
  language,
  llmConfig,
  busy,
  hasDataset,
  onToggleLanguage,
  onOpenSettings,
  onUploadFiles,
  onOpenMimic,
  onOpenComposer,
}: HeaderProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  const isConfigured = llmConfig.mock || llmConfig.has_api_key;
  const statusClass = llmConfig.mock ? "mock" : isConfigured ? "ready" : "";
  const statusText = llmConfig.mock
    ? language === "zh"
      ? "Mock 模式"
      : "Mock Mode"
    : llmConfig.has_api_key
    ? `${language === "zh" ? "已连接" : "Ready"} · ${llmConfig.model}`
    : language === "zh"
    ? "未配置 API Key"
    : "API Not Configured";

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

      <span className="sub">
        {language === "zh"
          ? "出版级科研数据可视化工作台 · LLM 智能驱动"
          : "Publication-Grade Scientific Plotting Workbench · LLM-Powered"}
      </span>

      <div className="header-tools">
        <div className={`llm-status ${statusClass}`} title={statusText}>
          <span className="status-dot" />
          <span>{statusText}</span>
        </div>

        {hasDataset && onOpenMimic && (
          <button className="btn secondary" onClick={onOpenMimic} disabled={busy} title="上传论文图照片或选择模板进行版式复刻">
            <span>🎨</span>
            <span>{language === "zh" ? "论文图复刻" : "Mimic"}</span>
          </button>
        )}

        {hasDataset && onOpenComposer && (
          <button className="btn secondary" onClick={onOpenComposer} disabled={busy} title="将多个子图拼版为组合大图 (Nature/Cell 风格)">
            <span>📊</span>
            <span>{language === "zh" ? "多图拼版" : "Composer"}</span>
          </button>
        )}

        <button className="btn secondary" onClick={onToggleLanguage} disabled={busy} title="切换中英文 / Switch Language">
          <span>🌐</span>
          <span>{language === "zh" ? "EN" : "中文"}</span>
        </button>

        <button className="btn secondary" onClick={onOpenSettings} disabled={busy} title="配置 API Key 与模型参数">
          <span>⚙️</span>
          <span>{language === "zh" ? "设置" : "Settings"}</span>
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

        <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy}>
          <span>📁</span>
          <span>{language === "zh" ? "导入数据" : "Import Data"}</span>
        </button>
      </div>
    </header>
  );
}
