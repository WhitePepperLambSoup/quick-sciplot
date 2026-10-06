import { useState } from "react";
import type { CodeParameter, PlotResult, StatementCard } from "../types";
import { CodeEditor } from "./CodeEditor";
import { ParameterInput, type Language } from "./ParameterInput";

interface CodeWorkbenchProps {
  language: Language;
  result: PlotResult;
  editorCode: string;
  activeCard: StatementCard | null;
  busy: boolean;
  onChangeEditorCode: (code: string) => void;
  onSelectCard: (card: StatementCard) => void;
  onApplyParameter: (parameter: CodeParameter, value: string) => Promise<void>;
  onRunEditor: () => Promise<void>;
  onCopyCode?: (code: string, ok: boolean) => void;
}

export function CodeWorkbench({
  language,
  result,
  editorCode,
  activeCard,
  busy,
  onChangeEditorCode,
  onSelectCard,
  onApplyParameter,
  onRunEditor,
  onCopyCode,
}: CodeWorkbenchProps) {
  const [copied, setCopied] = useState(false);
  const errorLine = result.run.success ? null : result.run.error_line ?? null;

  const handleCopy = async () => {
    const textToCopy = editorCode || result.code;
    try {
      await navigator.clipboard.writeText(textToCopy);
    } catch {
      // 剪贴板权限被拒绝或不可用时，不能显示“已复制”。
      onCopyCode?.(textToCopy, false);
      return;
    }
    setCopied(true);
    onCopyCode?.(textToCopy, true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="code-panel">
      <div className="code-panel-heading">
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <h2>
            <span>💻</span>
            <span>{language === "zh" ? "代码工作台与参数微调" : "Code Workbench & Tuning"}</span>
          </h2>
          <span>
            {language === "zh"
              ? "点击代码行定位对应片段；修改参数失焦后自动重新渲染"
              : "Click a line to locate its AST card; edit parameters to auto-redraw"}
          </span>
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          <button className="btn secondary small" onClick={() => void handleCopy()} disabled={busy}>
            <span>{copied ? "✓" : "📋"}</span>
            <span>{copied ? (language === "zh" ? "已复制！" : "Copied!") : (language === "zh" ? "复制代码" : "Copy Code")}</span>
          </button>
          <button className="btn small" onClick={onRunEditor} disabled={busy}>
            <span>▶</span>
            <span>{busy ? (language === "zh" ? "执行中…" : "Running…") : (language === "zh" ? "运行代码" : "Run Code")}</span>
          </button>
        </div>
      </div>

      <div className="code-workbench">
        {/* Column 1: Dark Line Viewer */}
        <div className="line-viewer" aria-label="带行号的完整代码">
          {result.code.split("\n").map((line, index) => {
            const lineNumber = index + 1;
            const statement = result.statements.find(
              (item) => lineNumber >= item.start && lineNumber <= item.end,
            );
            const active = Boolean(
              activeCard && lineNumber >= activeCard.start && lineNumber <= activeCard.end,
            );
            return (
              <div
                key={lineNumber}
                className={`code-line${active ? " active" : ""}${lineNumber === errorLine ? " error-line" : ""}`}
                onClick={() => statement && onSelectCard(statement)}
                title={statement ? `${statement.label} (L${statement.start}-L${statement.end})` : undefined}
              >
                <span className="code-line-number">{lineNumber}</span>
                <code>{line || " "}</code>
              </div>
            );
          })}
        </div>

        {/* Column 2: AST Statement Cards */}
        <div className="cards">
          {result.statements.map((s, i) => (
            <div
              key={`${s.start}-${s.end}-${i}`}
              className={`card ${activeCard?.start === s.start ? "active" : ""}`}
              onClick={() => onSelectCard(s)}
            >
              <div className="card-head">
                <span className="label">
                  {s.label || (language === "zh" ? "绘图片段" : "Statement")}
                </span>
                <span className="lines">
                  L{s.start}–{s.end}
                </span>
              </div>
              {(s.explanation_zh || s.explanation_en) && (
                <div className="statement-explanation">
                  <strong>{s.explanation_zh}</strong>
                  <small>{s.explanation_en}</small>
                </div>
              )}
              {s.data_bindings.length > 0 && (
                <div className="data-bindings">
                  {s.data_bindings.map((binding) => (
                    <span key={`${binding.axis}-${binding.column}`}>
                      {binding.axis} → {binding.column}
                    </span>
                  ))}
                </div>
              )}
              <pre className="card-code">{s.code}</pre>
              {s.parameters.length > 0 && (
                <div className="parameter-list" onClick={(e) => e.stopPropagation()}>
                  {s.parameters.map((parameter) => (
                    <ParameterInput
                      key={parameter.id}
                      parameter={parameter}
                      disabled={busy}
                      onApply={onApplyParameter}
                      language={language}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Column 3: Editable Python Code Area */}
        <div className="editor">
          <div className="editor-header">
            <div className="editor-label">
              <span>{language === "zh" ? "Python 绘图源码（可直接编辑，Ctrl+Enter 运行）" : "Python script (editable, Ctrl+Enter to run)"}</span>
            </div>
            {errorLine && editorCode === result.code && (
              <span className="editor-error-badge">{language === "zh" ? `第 ${errorLine} 行出错` : `Error on line ${errorLine}`}</span>
            )}
          </div>
          <CodeEditor
            value={editorCode}
            onChange={onChangeEditorCode}
            errorLine={editorCode === result.code ? errorLine : null}
            onRun={() => {
              if (!busy) void onRunEditor();
            }}
          />
        </div>
      </div>
    </section>
  );
}
