import { isCategoricalColumn, isNumericColumn } from "../columns";
import type { ChatMessage, DatasetInfo } from "../types";
import type { Language } from "./ParameterInput";

interface ChatPanelProps {
  language: Language;
  dataset?: DatasetInfo | null;
  messages: ChatMessage[];
  input: string;
  busy: boolean;
  disabled: boolean;
  onChangeInput: (val: string) => void;
  onSend: () => void;
}

export function ChatPanel({
  language,
  dataset,
  messages,
  input,
  busy,
  disabled,
  onChangeInput,
  onSend,
}: ChatPanelProps) {
  // 根据数据集结构智能推导 3-4 个科研级绘图目标建议 (LIDA 风格)
  const generateSuggestions = (): string[] => {
    if (!dataset) return [];
    const cols = dataset.summary.columns;
    const catCols = cols.filter(isCategoricalColumn);
    const numCols = cols.filter(isNumericColumn);

    const items: string[] = [];
    if (catCols.length > 0 && numCols.length > 0) {
      items.push(
        language === "zh"
          ? `按 ${catCols[0].name} 分组绘制 ${numCols[0].name} 的箱线图并叠加半透明抖动散点`
          : `Grouped boxplot of ${numCols[0].name} by ${catCols[0].name} with jitter stripplot`
      );
      items.push(
        language === "zh"
          ? `各 ${catCols[0].name} 组别的 ${numCols[0].name} 均值柱状图，附带标准差误差棒 (SD)`
          : `Bar chart of ${numCols[0].name} by ${catCols[0].name} with SD error bars`
      );
    }
    if (numCols.length >= 2) {
      items.push(
        language === "zh"
          ? `绘制 ${numCols[0].name} 与 ${numCols[1].name} 的学术散点图并添加线性回归拟合线`
          : `Scatter plot of ${numCols[0].name} vs ${numCols[1].name} with linear regression fit line`
      );
    }
    if (numCols.length >= 3) {
      items.push(
        language === "zh"
          ? `计算各数值指标间的 Pearson 相关系数，绘制带数值标注的下三角热图`
          : `Triangular correlation heatmap with Pearson r values and colorbar`
      );
    } else if (items.length < 3) {
      items.push(
        language === "zh"
          ? "绘制核密度估计 (KDE) 分布图，展示数据分布特征"
          : "Kernel density estimation (KDE) plot showing distribution characteristics"
      );
    }
    return items.slice(0, 3);
  };

  const suggestions = generateSuggestions();

  return (
    <section className="panel right">
      <div className="panel-header">
        <h2>
          <span>💬</span>
          <span>{language === "zh" ? "AI 绘图助手" : "AI SciPlot Copilot"}</span>
        </h2>
        {busy && (
          <span className="panel-tag" style={{ color: "var(--primary-600)", fontWeight: 500 }}>
            {language === "zh" ? "思考生成中…" : "Generating…"}
          </span>
        )}
      </div>

      <div className="chat">
        {messages.length === 0 && dataset && (
          <div className="chat-welcome">
            <p className="welcome-title">
              <span>✨</span>
              <span>{language === "zh" ? "数据集就绪，请描述您的绘图意图" : "Dataset Ready! Describe Your Plot"}</span>
            </p>
            <p className="welcome-sub">
              {language === "zh"
                ? "输入自然语言指令（例如“绘制箱线图并在旁边展示各组分布”），或点击下方智能推荐目标直接生成："
                : "Type in plain English (or Chinese), or pick a smart recommendation below:"}
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}${m.error ? " error" : ""}`}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px", fontSize: "11px", fontWeight: 600, opacity: 0.8 }}>
              <span>{m.role === "user" ? "👤" : "🤖"}</span>
              <span>{m.role === "user" ? (language === "zh" ? "我" : "You") : "SciPlot Assistant"}</span>
            </div>
            <div>{m.content}</div>
          </div>
        ))}
      </div>

      {dataset && suggestions.length > 0 && (
        <div className="suggestions-box">
          <div className="suggestions-label">
            <span>💡</span>
            <span>{language === "zh" ? "根据当前数据推荐的目标：" : "Smart Recommendations:"}</span>
          </div>
          <div className="suggestion-chips">
            {suggestions.map((s, idx) => (
              <button
                key={idx}
                type="button"
                className="suggestion-chip"
                onClick={() => onChangeInput(s)}
                disabled={busy}
                title="点击填入输入框"
              >
                <span>✨ </span>
                <span>{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-input">
        <textarea
          value={input}
          onChange={(e) => onChangeInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder={
            language === "zh"
              ? "描述绘图需求，如：按处理组绘制测量值箱线图，带抖动散点…"
              : "e.g., Draw a boxplot comparing treatments with jitter points..."
          }
          rows={3}
          disabled={disabled || busy}
        />
        <div className="chat-input-footer">
          <span className="input-hint">
            {language === "zh" ? "Enter ↵ 发送 / Shift+Enter 换行" : "Enter ↵ to send / Shift+Enter for newline"}
          </span>
          <button className="btn" onClick={onSend} disabled={busy || disabled || !input.trim()}>
            {busy ? (
              <span>{language === "zh" ? "生成中…" : "Generating…"}</span>
            ) : (
              <>
                <span>🚀</span>
                <span>{language === "zh" ? "发送" : "Send"}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
}
