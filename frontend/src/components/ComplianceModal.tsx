import { useEffect, useState } from "react";
import { checkCompliance, fitJournal } from "../api";
import type { PlotResult } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface ComplianceModalProps {
  language: Language;
  revisionId: string;
  datasetId?: string;
  code?: string;
  preset?: string;
  isPlotly?: boolean;
  onClose: () => void;
  onApplyPrompt?: (prompt: string) => void;
  onFitted?: (result: PlotResult, label: string) => void;
}

export function ComplianceModal({
  language,
  revisionId,
  datasetId,
  code,
  preset,
  isPlotly,
  onClose,
  onApplyPrompt,
  onFitted,
}: ComplianceModalProps) {
  const [journal, setJournal] = useState<"nature" | "ieee" | "cell">("nature");
  const [fitting, setFitting] = useState(false);
  useEscape(onClose, !fitting);

  const fit = async (column: "single" | "double") => {
    if (!datasetId || !code || !onFitted) return;
    setFitting(true);
    setError(null);
    try {
      const result = await fitJournal({ dataset_id: datasetId, code, journal, column, preset });
      const label =
        language === "zh"
          ? `${journal.toUpperCase()} ${column === "single" ? "单栏" : "双栏"}（${result.width_inches} in）`
          : `${journal.toUpperCase()} ${column} column (${result.width_inches} in)`;
      onFitted(result, label);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setFitting(false);
    }
  };
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<{
    journal: string;
    passed: boolean;
    checks: { item: string; passed: boolean; detail: string }[];
    formats_found: string[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    checkCompliance(revisionId, journal)
      .then((res) => {
        if (active) setReport(res);
      })
      .catch((err) => {
        if (active) setError(String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [revisionId, journal]);

  const handleFillPrompt = () => {
    if (!report) return;
    const failed = report.checks.filter((c) => !c.passed);
    const fixes = failed.map((c) => c.detail).join("；");
    const prompt =
      language === "zh"
        ? `请根据 ${journal.toUpperCase()} 出版合规审查建议调整图表代码：${fixes || "优化字体层级与排版尺寸，确保符合期刊矢量规范"}`
        : `Please adjust plot code to comply with ${journal.toUpperCase()} standards: ${fixes || "optimize font hierarchy and vector compliance"}`;
    onApplyPrompt?.(prompt);
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog compliance-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{language === "zh" ? "📋 学术顶刊出版合规审查 (Journal Compliance)" : "📋 Journal Compliance Checker"}</h3>
          <button className="btn-icon" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <div className="journal-tabs">
            {(["nature", "ieee", "cell"] as const).map((j) => (
              <button
                key={j}
                type="button"
                className={`journal-tab ${journal === j ? "active" : ""}`}
                onClick={() => setJournal(j)}
              >
                {j === "nature" && "Nature Portfolio"}
                {j === "ieee" && "IEEE Transactions"}
                {j === "cell" && "Cell Press"}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="compliance-loading">
              {language === "zh" ? "正在比对期刊投稿技术规范..." : "Auditing compliance against guidelines..."}
            </div>
          ) : error ? (
            <div className="error-alert">{error}</div>
          ) : report ? (
            <div className="compliance-content">
              <div className={`compliance-status-banner ${report.passed ? "passed" : "warning"}`}>
                <div className="status-title">
                  {report.passed
                    ? language === "zh"
                      ? "✓ 全部出版规范检查已通过"
                      : "✓ All Compliance Checks Passed"
                    : language === "zh"
                    ? "⚠️ 检测到需优化的期刊排版项目"
                    : "⚠️ Items need adjustment for publication"}
                </div>
                <div className="status-sub">
                  {language === "zh"
                    ? `目标出版标准：${report.journal.toUpperCase()} · 已就绪格式: ${report.formats_found.join(", ") || "无"}`
                    : `Target: ${report.journal.toUpperCase()} · Formats: ${report.formats_found.join(", ") || "None"}`}
                </div>
              </div>

              <div className="checks-list">
                {report.checks.map((chk, i) => (
                  <div key={i} className={`check-item ${chk.passed ? "pass" : "fail"}`}>
                    <div className="check-icon">{chk.passed ? "✓" : "!"}</div>
                    <div className="check-info">
                      <div className="check-name">{chk.item}</div>
                      <div className="check-detail">{chk.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="modal-footer">
          {onFitted && datasetId && code && !isPlotly && (
            <div className="compliance-fit">
              <span>{language === "zh" ? "一键适配版面宽度：" : "Fit width:"}</span>
              <button className="btn secondary small" disabled={fitting} onClick={() => void fit("single")}>
                {language === "zh" ? "单栏" : "Single column"}
              </button>
              <button className="btn secondary small" disabled={fitting} onClick={() => void fit("double")}>
                {language === "zh" ? "双栏" : "Double column"}
              </button>
            </div>
          )}
          <button className="btn secondary" onClick={onClose} disabled={fitting}>
            {language === "zh" ? "关闭" : "Close"}
          </button>
          {onApplyPrompt && report && !report.passed && (
            <button className="btn" onClick={handleFillPrompt} disabled={fitting}>
              {language === "zh" ? "填入合规优化指令到对话框" : "Apply Fixes to Chat"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
