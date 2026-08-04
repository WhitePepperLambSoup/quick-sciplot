import { useCallback, useEffect, useRef, useState } from "react";
import { editPlot, generatePlot, listPresets, runCode, uploadDataset } from "./api";
import type { ChatMessage, DatasetInfo, PlotResult, Preset, StatementCard } from "./types";

export default function App() {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState("default");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [result, setResult] = useState<PlotResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [editorCode, setEditorCode] = useState("");
  const [activeCard, setActiveCard] = useState<StatementCard | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const selectedPresetInfo = presets.find((preset) => preset.id === selectedPreset);

  useEffect(() => {
    listPresets().then(setPresets).catch(() => setPresets([]));
  }, []);

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
      setMessages((m) => [
        ...m,
        res.run.success
          ? { role: "assistant", content: "图已生成 ✓" }
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

  return (
    <div className="app">
      <header className="header">
        <h1>Quick SciPlot</h1>
        <span className="sub">LLM 驱动的快捷科研画图</span>
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
        </section>

        <section className="panel center">
          <h2>预览</h2>
          {result?.run.success && result.run.image ? (
            <img className="plot-img" src={result.run.image} alt="生成的图表" />
          ) : (
            <p className="hint">在右侧描述要画的图，结果会显示在这里。</p>
          )}
          {result && !result.run.success && <pre className="error">{result.run.stderr}</pre>}
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
          <h2>代码定位</h2>
          <div className="cards">
            {result.statements.map((s, i) => (
              <div
                key={i}
                className={`card ${activeCard?.start === s.start ? "active" : ""}`}
                onClick={() => {
                  setActiveCard(s);
                  const lines = result.code.split("\n").slice(s.start - 1, s.end);
                  setEditorCode(lines.join("\n"));
                }}
              >
                <div className="card-head">
                  <span className="lines">L{s.start}–{s.end}</span>
                  <span className="label">{s.label || "代码片段"}</span>
                </div>
                <pre className="card-code">{s.code}</pre>
              </div>
            ))}
          </div>
          <div className="editor">
            <textarea value={editorCode} onChange={(e) => setEditorCode(e.target.value)} spellCheck={false} />
            <button className="btn" onClick={runEditor} disabled={busy}>
              运行此代码
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
