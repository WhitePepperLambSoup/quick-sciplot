import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyParameter,
  editPlot,
  getConfig,
  generatePlot,
  listHistory,
  listPresets,
  restoreRevision,
  runCode,
  testLLMConnection,
  updateLLMConfig,
  uploadDataset,
} from "./api";
import type {
  ChatMessage,
  CodeParameter,
  ConnectionResult,
  DatasetInfo,
  LLMConfig,
  PlotResult,
  PlotlyFigure,
  Preset,
  RevisionSummary,
  StatementCard,
} from "./types";

interface ParameterInputProps {
  parameter: CodeParameter;
  disabled: boolean;
  onApply: (parameter: CodeParameter, value: string) => Promise<void>;
}

const MODEL_OPTIONS = ["deepseek-chat", "deepseek-reasoner", "gpt-4o-mini", "qwen-plus", "glm-4.5", "gemini-2.0-flash"];

const FALLBACK_PRESETS: Preset[] = [
  { id: "default", name: "默认", description: "Matplotlib 默认风格，适合快速预览。", source: "内置", source_url: "", category: "基础", local_available: false, has_fallback: true },
  { id: "science", name: "SciencePlots 科研", description: "简洁、细线、内向刻度，适合一般科研论文。", source: "SciencePlots", source_url: "", category: "论文", local_available: false, has_fallback: true },
  { id: "science-nature", name: "Nature 期刊", description: "Nature 论文常用的紧凑无衬线风格。", source: "SciencePlots", source_url: "", category: "期刊", local_available: false, has_fallback: true },
  { id: "science-ieee", name: "IEEE 期刊", description: "适合 IEEE 单栏论文的紧凑黑白友好风格。", source: "SciencePlots", source_url: "", category: "期刊", local_available: false, has_fallback: true },
  { id: "science-bright", name: "SciencePlots 色盲友好", description: "适合多系列数据的色盲友好配色。", source: "SciencePlots", source_url: "", category: "配色", local_available: false, has_fallback: true },
  { id: "lovely", name: "LovelyPlots 论文", description: "干净、可编辑，适合论文和学位论文排版。", source: "LovelyPlots", source_url: "", category: "论文", local_available: false, has_fallback: true },
  { id: "tueplots", name: "期刊尺寸（tueplots）", description: "按出版物尺寸和字体层级组织的基础风格。", source: "tueplots", source_url: "", category: "尺寸", local_available: false, has_fallback: true },
];

const DEFAULT_LLM_CONFIG: LLMConfig = {
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  mock: false,
  has_api_key: false,
  api_key_masked: "",
  auto_repair_attempts: 1,
  sandbox_timeout: 60,
  sandbox_mode: "process",
};

function ParameterInput({ parameter, disabled, onApply }: ParameterInputProps) {
  const [value, setValue] = useState(parameter.value);

  useEffect(() => {
    setValue(parameter.value);
  }, [parameter.value]);

  const commit = () => {
    if (!disabled && value !== parameter.value) {
      void onApply(parameter, value);
    }
  };

  return (
    <label className="parameter-field">
      <span>{parameter.label}</span>
      <input
        type={parameter.type === "number" ? "number" : "text"}
        value={value}
        disabled={disabled}
        title={`源码位置 L${parameter.start_line}`}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}

function InteractivePlot({ figure }: { figure: PlotlyFigure }) {
  const plotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    let disposed = false;
    void import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      void Plotly.newPlot(element, figure.data, figure.layout || {}, {
        responsive: true,
        displaylogo: false,
      });
    });
    return () => {
      disposed = true;
      void import("plotly.js-dist-min").then(({ default: Plotly }) => Plotly.purge(element));
    };
  }, [figure]);

  return <div ref={plotRef} className="interactive-plot" aria-label="交互式 Plotly 图表" />;
}

interface SettingsDialogProps {
  config: LLMConfig;
  onClose: () => void;
  onSaved: (config: LLMConfig) => void;
}

function SettingsDialog({ config, onClose, onSaved }: SettingsDialogProps) {
  const [baseUrl, setBaseUrl] = useState(config.base_url);
  const [model, setModel] = useState(config.model);
  const [modelChoice, setModelChoice] = useState(MODEL_OPTIONS.includes(config.model) ? config.model : "custom");
  const [apiKey, setApiKey] = useState("");
  const [mock, setMock] = useState(config.mock);
  const [repairAttempts, setRepairAttempts] = useState(String(config.auto_repair_attempts));
  const [sandboxMode, setSandboxMode] = useState<"process" | "docker">(config.sandbox_mode);
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
      });
      setApiKey("");
      onSaved(next);
      setMessage("配置已保存");
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
      setMessage(`连接成功，延迟 ${result.latency_ms} ms`);
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
            <h2 id="settings-title">模型设置</h2>
            <p>配置保存在本机用户目录，不会通过配置接口返回完整密钥。</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭设置">×</button>
        </div>
        <label className="settings-field">
          <span>OpenAI 兼容 Base URL</span>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" />
        </label>
        <label className="settings-field">
          <span>模型名称</span>
          <select
            value={modelChoice}
            onChange={(e) => {
              const value = e.target.value;
              setModelChoice(value);
              if (value !== "custom") setModel(value);
            }}
          >
            {MODEL_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
            <option value="custom">自定义模型…</option>
          </select>
          {modelChoice === "custom" && (
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="输入模型名称" />
          )}
        </label>
        <label className="settings-field">
          <span>API Key {config.has_api_key && <small>当前：{config.api_key_masked}</small>}</span>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="留空表示保持当前密钥" autoComplete="new-password" />
        </label>
        <div className="settings-row">
          <label className="settings-check">
            <input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} />
            <span>Mock 演示模式</span>
          </label>
          <label className="settings-field compact">
            <span>自动修复次数（0–3）</span>
            <input type="number" min="0" max="3" value={repairAttempts} onChange={(e) => setRepairAttempts(e.target.value)} />
          </label>
        </div>
        <label className="settings-field">
          <span>代码执行隔离</span>
          <select value={sandboxMode} onChange={(e) => setSandboxMode(e.target.value as "process" | "docker")}>
            <option value="process">本地受限进程（无需 Docker）</option>
            <option value="docker">Docker 强隔离（需先构建镜像）</option>
          </select>
        </label>
        {message && <p className={`settings-message${connection ? " success" : ""}`}>{message}</p>}
        <div className="settings-actions">
          <button className="btn secondary" onClick={test} disabled={busy}>测试当前连接</button>
          <button className="btn" onClick={save} disabled={busy}>{busy ? "处理中…" : "保存配置"}</button>
        </div>
      </section>
    </div>
  );
}

const OPERATION_LABELS: Record<string, string> = {
  generate: "生成",
  edit: "对话调整",
  parameter: "参数调整",
  run: "代码运行",
  restore: "恢复版本",
};

export default function App() {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [presets, setPresets] = useState<Preset[]>(FALLBACK_PRESETS);
  const [selectedPreset, setSelectedPreset] = useState("default");
  const [history, setHistory] = useState<RevisionSummary[]>([]);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(DEFAULT_LLM_CONFIG);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [result, setResult] = useState<PlotResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [editorCode, setEditorCode] = useState("");
  const [activeCard, setActiveCard] = useState<StatementCard | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const selectedPresetInfo = presets.find((preset) => preset.id === selectedPreset);

  useEffect(() => {
    let disposed = false;
    let attempts = 0;
    let timer: number | undefined;
    const loadBackendMetadata = async () => {
      try {
        const [nextPresets, nextConfig] = await Promise.all([listPresets(), getConfig()]);
        if (disposed) return;
        if (nextPresets.length > 0) setPresets(nextPresets);
        setLlmConfig(nextConfig);
      } catch {
        if (!disposed && attempts++ < 20) {
          timer = window.setTimeout(loadBackendMetadata, 1000);
        }
      }
    };
    void loadBackendMetadata();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    const datasetId = dataset?.id;
    if (!datasetId) {
      setHistory([]);
      return;
    }
    listHistory(datasetId).then(setHistory).catch(() => setHistory([]));
  }, [dataset?.id]);

  const refreshHistory = async (datasetId: string) => {
    try {
      setHistory(await listHistory(datasetId));
    } catch {
      // 历史记录不是绘图主流程的阻塞条件。
    }
  };

  const handleUpload = async (file: File) => {
    setBusy(true);
    try {
      const ds = await uploadDataset(file);
      setDataset(ds);
      setResult(null);
      setMessages([{ role: "assistant", content: `数据已导入：${ds.summary.shape.rows} 行 × ${ds.summary.shape.cols} 列。请告诉我你想画什么样的图。` }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !dataset || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = result
        ? await editPlot(dataset.id, result.code, text, selectedPreset)
        : await generatePlot(dataset.id, text, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      setMessages((m) => [
        ...m,
        res.run.success
          ? { role: "assistant", content: res.repair_attempts ? `图已生成，自动修复 ${res.repair_attempts} 次 ✓` : "图已生成 ✓" }
          : { role: "assistant", content: "生成失败：" + (res.run.stderr || "无错误信息"), error: true },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  }, [input, dataset, busy, result, selectedPreset]);

  const runEditor = async () => {
    if (!dataset) return;
    setBusy(true);
    try {
      const res = await runCode(dataset.id, editorCode, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      setMessages((m) => [
        ...m,
        res.run.success
          ? { role: "assistant", content: "编辑后的代码已重新渲染 ✓" }
          : { role: "assistant", content: "运行失败：" + (res.run.stderr || "无错误信息"), error: true },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const applyParameterChange = async (parameter: CodeParameter, value: string) => {
    if (!dataset || !result || busy) return;
    setBusy(true);
    try {
      const res = await applyParameter(dataset.id, result.code, parameter, value, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      setActiveCard(
        res.statements.find((statement) => statement.start <= parameter.start_line && statement.end >= parameter.start_line) ?? null,
      );
      setMessages((m) => [...m, { role: "assistant", content: `已应用“${parameter.label}”并重新渲染 ✓` }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revision: RevisionSummary) => {
    if (!dataset || busy || !revision.success) return;
    setBusy(true);
    try {
      const res = await restoreRevision(revision.id);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      setActiveCard(null);
      await refreshHistory(dataset.id);
      setMessages((m) => [...m, { role: "assistant", content: "已恢复历史版本并生成新版本 ✓" }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <h1>Quick SciPlot</h1>
        <span className="sub">LLM 驱动的快捷科研画图</span>
        <span className={`llm-status${llmConfig.mock || llmConfig.has_api_key ? " ready" : ""}`}>
          {llmConfig.mock ? "Mock 模式" : llmConfig.has_api_key ? `已配置 · ${llmConfig.model}` : "未配置 API"}
        </span>
        <button className="btn secondary" onClick={() => setSettingsOpen(true)} disabled={busy}>
          模型设置
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
          hidden
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
        />
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy}>
          导入数据
        </button>
      </header>

      <main className="layout">
        <section className="panel left">
          <h2>数据</h2>
          <div className="preset-picker">
            <label htmlFor="preset-select">图表风格</label>
            <select
              id="preset-select"
              value={selectedPreset}
              onChange={(e) => setSelectedPreset(e.target.value)}
              disabled={busy}
            >
              {presets.length === 0 ? (
                <option value="default">默认</option>
              ) : (
                presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))
              )}
            </select>
            {selectedPresetInfo && (
              <>
                <p className="preset-description">{selectedPresetInfo.description}</p>
                <p className="preset-source">
                  {selectedPresetInfo.local_available ? "● 本地预设已启用" : "○ 使用内置兜底"}
                  {selectedPresetInfo.source && ` · ${selectedPresetInfo.source}`}
                </p>
              </>
            )}
          </div>
          {!dataset ? (
            <p className="hint">点击右上角"导入数据"，支持 CSV / TSV / Excel / JSON。</p>
          ) : (
            <>
              <p className="meta">
                {dataset.summary.shape.rows} 行 × {dataset.summary.shape.cols} 列
              </p>
              <table className="summary">
                <thead>
                  <tr>
                    <th>列名</th>
                    <th>类型</th>
                    <th>缺失</th>
                    <th>统计</th>
                  </tr>
                </thead>
                <tbody>
                  {dataset.summary.columns.map((c) => (
                    <tr key={c.name}>
                      <td className="mono">{c.name}</td>
                      <td>{c.dtype}</td>
                      <td>{c.nulls}</td>
                      <td className="mono small">
                        {c.mean !== undefined ? `均值 ${c.mean}` : c.top_values?.[0] ? `最多 ${c.top_values[0].value}(${c.top_values[0].count})` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
           )}
          {dataset && (
            <div className="history-section">
              <div className="history-heading">
                <span>版本历史</span>
                <span className="history-count">{history.length}</span>
              </div>
              {history.length === 0 ? (
                <p className="hint">生成第一张图后会自动记录版本。</p>
              ) : (
                <div className="history-list">
                  {history.slice(0, 12).map((revision) => (
                    <button
                      key={revision.id}
                      className={`history-item${revision.id === result?.revision_id ? " active" : ""}`}
                      disabled={busy || !revision.success}
                      onClick={() => void restore(revision)}
                      title={revision.success ? "恢复该版本" : "失败版本不可恢复"}
                    >
                      <span>{OPERATION_LABELS[revision.operation] || revision.operation}</span>
                      <span>{revision.preset}</span>
                      <small>{revision.created_at}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
         </section>

        <section className="panel center">
          <h2>预览</h2>
          {result?.run.success && result.run.interactive ? (
            <InteractivePlot figure={result.run.interactive} />
          ) : result?.run.success && result.run.image ? (
            <img className="plot-img" src={result.run.image} alt="生成的图表" />
          ) : (
            <p className="hint">在右侧描述要画的图，结果会显示在这里。</p>
          )}
          {result && !result.run.success && <pre className="error">{result.run.stderr}</pre>}
          {result?.run.success && result.revision_id && (
            <div className="export-actions">
              <span>导出：</span>
              {(["png", "svg", "pdf", "plotly"] as const)
                .filter((format) => result.export_formats.includes(format))
                .map((format) => (
                  <a
                    key={format}
                    className="export-link"
                    href={`/api/plots/revisions/${result.revision_id}/export/${format}`}
                    download
                  >
                    {format === "plotly" ? "JSON" : format.toUpperCase()}
                  </a>
                ))}
            </div>
          )}
        </section>

        <section className="panel right">
          <h2>AI 对话</h2>
          <div className="chat">
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}${m.error ? " error" : ""}`}>
                {m.content}
              </div>
            ))}
          </div>
          <div className="chat-input">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="例如：画柱状图，对比每年的 revenue，加标题"
              rows={2}
            />
            <button className="btn" onClick={send} disabled={busy || !dataset}>
              {busy ? "生成中…" : "发送"}
            </button>
          </div>
        </section>
      </main>

      {result && (
        <section className="code-panel">
          <div className="code-panel-heading">
            <h2>代码定位</h2>
            <span>点击片段定位源码；参数失焦后自动应用并重绘</span>
          </div>
          <div className="code-workbench">
            <div className="line-viewer" aria-label="带行号的完整代码">
              {result.code.split("\n").map((line, index) => {
                const lineNumber = index + 1;
                const statement = result.statements.find((item) => lineNumber >= item.start && lineNumber <= item.end);
                const active = Boolean(activeCard && lineNumber >= activeCard.start && lineNumber <= activeCard.end);
                return (
                  <div
                    key={lineNumber}
                    className={`code-line${active ? " active" : ""}`}
                    onClick={() => statement && setActiveCard(statement)}
                  >
                    <span className="code-line-number">{lineNumber}</span>
                    <code>{line || " "}</code>
                  </div>
                );
              })}
            </div>
            <div className="cards">
              {result.statements.map((s, i) => (
                <div
                  key={`${s.start}-${s.end}-${i}`}
                  className={`card ${activeCard?.start === s.start ? "active" : ""}`}
                  onClick={() => {
                    setActiveCard(s);
                    setEditorCode(result.code);
                  }}
                >
                  <div className="card-head">
                    <span className="lines">L{s.start}–{s.end}</span>
                    <span className="label">{s.label || "代码片段"}</span>
                  </div>
                  <pre className="card-code">{s.code}</pre>
                  {s.parameters.length > 0 && (
                    <div className="parameter-list" onClick={(e) => e.stopPropagation()}>
                      {s.parameters.map((parameter) => (
                        <ParameterInput
                          key={parameter.id}
                          parameter={parameter}
                          disabled={busy}
                          onApply={applyParameterChange}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="editor">
              <div className="editor-label">完整代码（可直接编辑）</div>
              <textarea value={editorCode} onChange={(e) => setEditorCode(e.target.value)} spellCheck={false} />
              <button className="btn" onClick={runEditor} disabled={busy}>
                {busy ? "执行中…" : "运行完整代码"}
              </button>
            </div>
          </div>
        </section>
      )}
      {settingsOpen && (
        <SettingsDialog config={llmConfig} onClose={() => setSettingsOpen(false)} onSaved={setLlmConfig} />
      )}
    </div>
  );
}
