import { useState } from "react";
import { listModels, testLLMConnection, updateLLMConfig } from "../api";
import type { ConnectionResult, LLMConfig } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface SettingsDialogProps {
  config: LLMConfig;
  onClose: () => void;
  onSaved: (config: LLMConfig) => void;
  onOpenSetup?: () => void;
  language: Language;
}

interface Provider {
  id: string;
  zh: string;
  en: string;
  baseUrl: string;
  models: string[];
  local?: boolean;
}

const PROVIDERS: Provider[] = [
  { id: "deepseek", zh: "DeepSeek", en: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", models: ["deepseek-chat", "deepseek-reasoner"] },
  { id: "openai", zh: "OpenAI", en: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-4o-mini", "gpt-4o"] },
  { id: "qwen", zh: "通义千问 (DashScope)", en: "Qwen (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen-plus", "qwen-max", "qwen-vl-plus"] },
  { id: "zhipu", zh: "智谱 GLM", en: "Zhipu GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", models: ["glm-4.5", "glm-4v-plus"] },
  { id: "ollama", zh: "Ollama（本机）", en: "Ollama (local)", baseUrl: "http://127.0.0.1:11434/v1", models: ["qwen2.5-coder:7b", "llama3.1:8b"], local: true },
  { id: "lmstudio", zh: "LM Studio（本机）", en: "LM Studio (local)", baseUrl: "http://127.0.0.1:1234/v1", models: [], local: true },
];

function detectProvider(baseUrl: string): string {
  const match = PROVIDERS.find((provider) => provider.baseUrl === baseUrl.replace(/\/+$/, ""));
  return match ? match.id : "custom";
}

function isLoopback(url: string): boolean {
  try {
    const host = new URL(url).hostname.replace(/^\[|\]$/g, "");
    return host === "localhost" || host === "::1" || host.startsWith("127.");
  } catch {
    return false;
  }
}

export function SettingsDialog({ config, onClose, onSaved, onOpenSetup, language }: SettingsDialogProps) {
  const zh = language === "zh";
  const [providerId, setProviderId] = useState(detectProvider(config.base_url));
  const [baseUrl, setBaseUrl] = useState(config.base_url);
  const [model, setModel] = useState(config.model);
  const [apiKey, setApiKey] = useState("");
  const [mock, setMock] = useState(config.mock);
  const [allowLoopback, setAllowLoopback] = useState(Boolean(config.allow_loopback_llm));
  const [repairAttempts, setRepairAttempts] = useState(String(config.auto_repair_attempts));
  const [sendDataValues, setSendDataValues] = useState(config.send_data_values);
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState<ConnectionResult | null>(null);
  useEscape(onClose, !busy);

  const provider = PROVIDERS.find((item) => item.id === providerId);
  const suggestions = Array.from(new Set([...(models.length ? models : provider?.models || []), model].filter(Boolean)));
  const localUrl = isLoopback(baseUrl);

  const chooseProvider = (id: string) => {
    setProviderId(id);
    const next = PROVIDERS.find((item) => item.id === id);
    if (!next) return;
    setBaseUrl(next.baseUrl);
    setModels([]);
    if (next.models[0]) setModel(next.models[0]);
    if (next.local) {
      setAllowLoopback(true);
      setMock(false);
    }
  };

  const save = async (): Promise<LLMConfig | null> => {
    setBusy(true);
    setMessage("");
    try {
      const next = await updateLLMConfig({
        ...(apiKey ? { api_key: apiKey } : {}),
        base_url: baseUrl,
        model,
        mock,
        auto_repair_attempts: Number(repairAttempts),
        send_data_values: sendDataValues,
        allow_loopback_llm: allowLoopback,
      });
      setApiKey("");
      onSaved(next);
      setMessage(zh ? "配置已保存" : "Configuration saved");
      return next;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const fetchModels = async () => {
    // Save first so the backend queries the endpoint the user is looking at.
    if (!(await save())) return;
    setBusy(true);
    try {
      const list = await listModels();
      setModels(list);
      setMessage(zh ? `获取到 ${list.length} 个模型` : `Found ${list.length} models`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    if (!(await save())) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await testLLMConnection();
      setConnection(result);
      setMessage(zh ? `连接成功，延迟 ${result.latency_ms} ms` : `Connected in ${result.latency_ms} ms`);
    } catch (error) {
      setConnection(null);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="settings-heading">
          <div>
            <h2 id="settings-title">{zh ? "模型设置" : "Model settings"}</h2>
            <p>{zh ? "支持任意 OpenAI 兼容接口，也支持 Ollama / LM Studio 等本机模型（数据不出本机）。" : "Any OpenAI-compatible API, or a local model such as Ollama / LM Studio (data stays on this machine)."}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label={zh ? "关闭设置" : "Close"} disabled={busy}>
            ×
          </button>
        </div>

        <label className="settings-field">
          <span>{zh ? "模型服务" : "Provider"}</span>
          <select value={providerId} onChange={(e) => chooseProvider(e.target.value)}>
            {PROVIDERS.map((item) => (
              <option key={item.id} value={item.id}>{zh ? item.zh : item.en}</option>
            ))}
            <option value="custom">{zh ? "自定义 OpenAI 兼容接口" : "Custom OpenAI-compatible"}</option>
          </select>
        </label>
        <label className="settings-field">
          <span>Base URL</span>
          <input
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              setProviderId(detectProvider(e.target.value));
            }}
            placeholder="https://api.deepseek.com/v1"
          />
        </label>
        <label className="settings-field">
          <span>
            {zh ? "模型名称" : "Model"}
            <button type="button" className="btn ghost small settings-inline-btn" onClick={() => void fetchModels()} disabled={busy}>
              {zh ? "从服务获取列表" : "Fetch list"}
            </button>
          </span>
          <input value={model} onChange={(e) => setModel(e.target.value)} list="model-suggestions" placeholder={zh ? "输入或选择模型名称" : "Type or pick a model"} />
          <datalist id="model-suggestions">
            {suggestions.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        </label>
        <label className="settings-field">
          <span>
            API Key{" "}
            {config.has_api_key && (
              <small>
                {zh ? "当前" : "Current"}: {config.api_key_masked}
              </small>
            )}
            {localUrl && <small>{zh ? "（本机模型通常不需要）" : "(usually not needed for local models)"}</small>}
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={zh ? "留空表示保持当前密钥" : "Leave blank to keep current key"}
            autoComplete="new-password"
          />
        </label>
        {localUrl && (
          <label className="settings-check">
            <input type="checkbox" checked={allowLoopback} onChange={(e) => setAllowLoopback(e.target.checked)} />
            <span>{zh ? "允许连接本机模型服务（仅 localhost / 127.0.0.1）" : "Allow a model server on this machine (localhost / 127.0.0.1 only)"}</span>
          </label>
        )}
        <div className="settings-row">
          <label className="settings-check">
            <input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} />
            <span>{zh ? "Mock 模式（不调用模型，用内置示例代码）" : "Mock mode (built-in sample code)"}</span>
          </label>
          <label className="settings-field compact">
            <span>{zh ? "自动修复次数（0–3）" : "Auto-repair attempts (0–3)"}</span>
            <input type="number" min="0" max="3" value={repairAttempts} onChange={(e) => setRepairAttempts(e.target.value)} />
          </label>
        </div>
        <label className="settings-check">
          <input type="checkbox" checked={sendDataValues} onChange={(e) => setSendDataValues(e.target.checked)} />
          <span>{zh ? "允许将脱敏后的分类数据值发送给模型（默认关闭）" : "Allow redacted categorical values to be sent to the model (off by default)"}</span>
        </label>
        {onOpenSetup && (
          <p className="settings-note">
            {zh ? "代码执行环境（Docker / 本地 worker）请在" : "Code execution (Docker / local worker) is configured in"}{" "}
            <button type="button" className="btn ghost small settings-inline-btn" onClick={onOpenSetup}>
              {zh ? "环境设置" : "Setup"}
            </button>
            {zh ? "中配置。" : "."}
          </p>
        )}
        {message && <p className={`settings-message${connection ? " success" : ""}`}>{message}</p>}
        <div className="settings-actions">
          <button className="btn secondary" onClick={() => void test()} disabled={busy}>
            {zh ? "保存并测试连接" : "Save & test"}
          </button>
          <button className="btn" onClick={() => void save()} disabled={busy}>
            {busy ? (zh ? "处理中…" : "Working…") : zh ? "保存配置" : "Save"}
          </button>
        </div>
      </section>
    </div>
  );
}
