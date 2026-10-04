import { useState } from "react";
import { annotateStats } from "../api";
import { isCategoricalColumn, isNumericColumn } from "../columns";
import type { DatasetInfo, PlotResult } from "../types";
import type { Language } from "./ParameterInput";

interface StatsModalProps {
  language: Language;
  dataset: DatasetInfo;
  code: string;
  onClose: () => void;
  onSuccess: (result: PlotResult) => void;
}

export function StatsModal({ language, dataset, code, onClose, onSuccess }: StatsModalProps) {
  const columns = dataset.summary.columns;
  const catColumns = columns.filter(isCategoricalColumn);
  const numColumns = columns.filter(isNumericColumn);

  const [groupCol, setGroupCol] = useState(catColumns[0]?.name || columns[0]?.name || "");
  const [valCol, setValCol] = useState(numColumns[0]?.name || columns[1]?.name || "");
  const [testType, setTestType] = useState<"auto" | "welch" | "mann-whitney">("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const groupsForColumn = (columnName: string): string[] => {
    const values = columns.find((c) => c.name === columnName)?.top_values?.map((tv) => tv.value) || [];
    return Array.from(new Set(values.filter((value) => value.trim().length > 0)));
  };

  // 获取当前所选分组列的可选组
  const availableGroups = groupsForColumn(groupCol);

  // 对比组对列表
  const [pairs, setPairs] = useState<[string, string][]>(() => {
    if (availableGroups.length >= 2) {
      return [[availableGroups[0], availableGroups[1]]];
    }
    return [];
  });

  const [newGroupA, setNewGroupA] = useState(availableGroups[0] || "");
  const [newGroupB, setNewGroupB] = useState(availableGroups[1] || availableGroups[0] || "");

  const addPair = () => {
    if (!newGroupA || !newGroupB || newGroupA === newGroupB) return;
    const exists = pairs.some(
      ([a, b]) => (a === newGroupA && b === newGroupB) || (a === newGroupB && b === newGroupA)
    );
    if (!exists) {
      setPairs([...pairs, [newGroupA, newGroupB]]);
    }
  };

  const removePair = (index: number) => {
    setPairs(pairs.filter((_, i) => i !== index));
  };

  const handleGroupColumnChange = (nextGroupCol: string) => {
    const nextGroups = groupsForColumn(nextGroupCol);
    setGroupCol(nextGroupCol);
    setPairs(nextGroups.length >= 2 ? [[nextGroups[0], nextGroups[1]]] : []);
    setNewGroupA(nextGroups[0] || "");
    setNewGroupB(nextGroups[1] || "");
  };

  const handleApply = async () => {
    if (!groupCol || !valCol || availableGroups.length < 2 || pairs.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await annotateStats({
        dataset_id: dataset.id,
        code,
        group_col: groupCol,
        val_col: valCol,
        pairs,
        test_type: testType,
      });
      onSuccess(res);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog stats-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{language === "zh" ? "⚡ 科研统计检验与显著性标尺" : "⚡ Statistical Significance & Brackets"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">
            {language === "zh"
              ? "自动计算指定分组间的假设检验（p 值），并在图表上方注入标准学术连线括号与星号标注（*** p<0.001, ** p<0.01, * p<0.05, ns）。"
              : "Calculates statistical significance between groups and injects standard publication bracket lines and asterisks."}
          </p>

          <div className="form-row">
            <div className="form-group">
              <label>{language === "zh" ? "分组列 (X 轴分类)" : "Group Column (X-axis)"}</label>
              <select
                value={groupCol}
                onChange={(e) => handleGroupColumnChange(e.target.value)}
                disabled={busy}
              >
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({c.dtype}, {c.n_unique} 类)
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>{language === "zh" ? "数值测量列 (Y 轴数据)" : "Value Column (Y-axis)"}</label>
              <select value={valCol} onChange={(e) => setValCol(e.target.value)} disabled={busy}>
                {numColumns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} (均值 {c.mean !== undefined ? c.mean.toFixed(2) : "-"})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label>{language === "zh" ? "检验方法" : "Test Type"}</label>
            <div className="radio-pills">
              <label className={`radio-pill ${testType === "auto" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="testType"
                  value="auto"
                  checked={testType === "auto"}
                  onChange={() => setTestType("auto")}
                />
                {language === "zh" ? "自动 (默认 Welch's t 检验)" : "Auto (Welch's t-test)"}
              </label>
              <label className={`radio-pill ${testType === "welch" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="testType"
                  value="welch"
                  checked={testType === "welch"}
                  onChange={() => setTestType("welch")}
                />
                Welch's t-test
              </label>
              <label className={`radio-pill ${testType === "mann-whitney" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="testType"
                  value="mann-whitney"
                  checked={testType === "mann-whitney"}
                  onChange={() => setTestType("mann-whitney")}
                />
                Mann-Whitney U (非参数)
              </label>
            </div>
          </div>

          <div className="form-group">
            <label>{language === "zh" ? "指定对比组对 (Pairs to compare)" : "Pairs to compare"}</label>
            <div className="pair-chips">
              {pairs.map(([a, b], idx) => (
                <span key={idx} className="pair-chip">
                  <strong>{a}</strong> vs <strong>{b}</strong>
                  <button type="button" onClick={() => removePair(idx)} disabled={busy}>×</button>
                </span>
              ))}
              {pairs.length === 0 && (
                <span className="empty-hint">{language === "zh" ? "请至少添加一组对比" : "Add at least one pair"}</span>
              )}
            </div>

            {availableGroups.length >= 2 && (
              <div className="add-pair-row">
                <select value={newGroupA} onChange={(e) => setNewGroupA(e.target.value)}>
                  {availableGroups.map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
                <span>vs</span>
                <select value={newGroupB} onChange={(e) => setNewGroupB(e.target.value)}>
                  {availableGroups.map((g) => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={addPair}
                  disabled={busy || !newGroupA || !newGroupB || newGroupA === newGroupB}
                >
                  {language === "zh" ? "+ 添加对比对" : "+ Add Pair"}
                </button>
              </div>
            )}
          </div>

          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>
            {language === "zh" ? "取消" : "Cancel"}
          </button>
          <button
            className="btn"
            onClick={handleApply}
            disabled={busy || availableGroups.length < 2 || pairs.length === 0}
          >
            {busy
              ? (language === "zh" ? "计算并注入中..." : "Calculating...")
              : (language === "zh" ? "计算检验并注入标尺" : "Compute & Inject Brackets")}
          </button>
        </div>
      </div>
    </div>
  );
}
