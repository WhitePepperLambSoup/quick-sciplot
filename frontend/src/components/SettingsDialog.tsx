import { useState } from "react";
import { testLLMConnection, updateLLMConfig } from "../api";
import type { ConnectionResult, LLMConfig } from "../types";
import type { Language } from "./ParameterInput";

interface SettingsDialogProps {
  config: LLMConfig;
  onClose: () => void;
  onSaved: (config: LLMConfig) => void;
  language: Language;
}

const MODEL_OPTIONS = [
  "deepseek-chat",
  "deepseek-reasoner",
  "gpt-4o-mini",
  "qwen-plus",
  "glm-4.5",
  "gemini-2.0-flash",
];

export function SettingsDialog({ config, onClose, onSaved, language }: SettingsDialogProps) {
  const [baseUrl, setBaseUrl] = useState(config.base_url);
  const [model, setModel] = useState(config.model);
  const [modelChoice, setModelChoice] = useState(MODEL_OPTIONS.includes(config.model) ? config.model : "custom");
  const [apiKey, setApiKey] = useState("");
  const [mock, setMock] = useState(config.mock);
  const [repairAttempts, setRepairAttempts] = useState(String(config.auto_repair_attempts));
  const [sandboxMode, setSandboxMode] = useState<"process" | "docker">(config.sandbox_mode);
  const [sendDataValues, setSendDataValues] = useState(config.send_data_values);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState<ConnectionResult | null>(null);

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      const next = await updateLLMConfig({
        ...(apiKey ? { api_key: apiKey } : {}),
        base_url: baseUrl,
        model,
        mock,
        auto_repair_attempts: Number(repairAttempts),
        sandbox_mode: sandboxMode,
        send_data_values: sendDataValues,
      });
      setApiKey("");
      onSaved(next);
      setMessage(language === "zh" ? "配置已保存" : "Configuration saved");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setMessage("");
    try {
      const result = await testLLMConnection();
      setConnection(result);
      setMessage(
        language === "zh"
          ? `连接成功，延迟 ${result.latency_ms} ms`
          : `Connected in ${result.latency_ms} ms`,
      );
    } catch (error) {
      setConnection(null);
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="settings-heading">
          <div>
            <h2 id="settings-title">{language === "zh" ? "模型设置" : "Model settings"}</h2>
            <p>
              {language === "zh"
                ? "配置保存在本机用户目录，通信支持会话握手防护。"
                : "Saved in the local user directory with session handshake protection."}
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭设置">
            ×
          </button>
        </div>
        <label className="settings-field">
          <span>OpenAI-compatible Base URL</span>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" />
        </label>
        <label className="settings-field">
          <span>{language === "zh" ? "模型名称" : "Model"}</span>
          <select
            value={modelChoice}
            onChange={(e) => {
              const value = e.target.value;
              setModelChoice(value);
              if (value !== "custom") setModel(value);
            }}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
            <option value="custom">{language === "zh" ? "自定义模型…" : "Custom model…"}</option>
          </select>
          {modelChoice === "custom" && (
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="输入模型名称" />
          )}
        </label>
        <label className="settings-field">
          <span>
            API Key{" "}
            {config.has_api_key && (
              <small>
                {language === "zh" ? "当前" : "Current"}: {config.api_key_masked}
              </small>
            )}
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={language === "zh" ? "留空表示保持当前密钥" : "Leave blank to keep current key"}
            autoComplete="new-password"
          />
        </label>
        <div className="settings-row">
          <label className="settings-check">
            <input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} />
            <span>{language === "zh" ? "Mock 模式" : "Mock mode"}</span>
          </label>
          <label className="settings-field compact">
            <span>{language === "zh" ? "自动修复次数（0–3）" : "Auto-repair attempts (0–3)"}</span>
            <input
              type="number"
              min="0"
              max="3"
              value={repairAttempts}
              onChange={(e) => setRepairAttempts(e.target.value)}
            />
          </label>
        </div>
        <label className="settings-field">
          <span>{language === "zh" ? "代码执行隔离" : "Code execution isolation"}</span>
          <select value={sandboxMode} onChange={(e) => setSandboxMode(e.target.value as "process" | "docker")}>
            <option value="process">
              {language === "zh" ? "本地受限进程（无需 Docker）" : "Local worker (no Docker)"}
            </option>
            <option value="docker">
              {language === "zh" ? "Docker 强隔离（需先构建镜像）" : "Docker isolation (build image first)"}
            </option>
          </select>
        </label>
        <label className="settings-check">
          <input type="checkbox" checked={sendDataValues} onChange={(e) => setSendDataValues(e.target.checked)} />
          <span>
            {language === "zh"
              ? "允许将脱敏后的分类数据值发送给模型（默认关闭）"
              : "Allow redacted categorical values to be sent to the model (off by default)"}
          </span>
        </label>
        {message && <p className={`settings-message${connection ? " success" : ""}`}>{message}</p>}
        <div className="settings-actions">
          <button className="btn secondary" onClick={test} disabled={busy}>
            {language === "zh" ? "测试当前连接" : "Test connection"}
          </button>
          <button className="btn" onClick={save} disabled={busy}>
            {busy
              ? language === "zh"
                ? "处理中…"
                : "Working…"
              : language === "zh"
              ? "保存配置"
              : "Save"}
          </button>
        </div>
      </section>
    </div>
  );
}
