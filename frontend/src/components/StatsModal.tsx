import { useEffect, useState } from "react";
import { annotateStats, columnValues, regressionPlot } from "../api";
import { isCategoricalColumn, isNumericColumn } from "../columns";
import type { DatasetInfo, PlotResult } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface StatsModalProps {
  language: Language;
  dataset: DatasetInfo;
  code: string;
  preset?: string;
  onClose: () => void;
  onSuccess: (result: PlotResult, kind: "stats" | "regression") => void;
}

type TestType = "auto" | "mann-whitney" | "paired-t" | "wilcoxon" | "tukey";
const PAIRED: TestType[] = ["paired-t", "wilcoxon"];

export function StatsModal({ language, dataset, code, preset, onClose, onSuccess }: StatsModalProps) {
  const zh = language === "zh";
  const columns = dataset.summary.columns;
  const catColumns = columns.filter(isCategoricalColumn);
  const numColumns = columns.filter(isNumericColumn);

  const [tab, setTab] = useState<"stats" | "regression">("stats");
  const [groupCol, setGroupCol] = useState(catColumns[0]?.name || columns[0]?.name || "");
  const [valCol, setValCol] = useState(numColumns[0]?.name || columns[1]?.name || "");
  const [testType, setTestType] = useState<TestType>("auto");
  const [correction, setCorrection] = useState("bonferroni");
  const [pairCol, setPairCol] = useState("");
  const [groups, setGroups] = useState<string[]>([]);
  const [groupsTruncated, setGroupsTruncated] = useState(false);
  const [pairs, setPairs] = useState<[string, string][]>([]);
  const [newGroupA, setNewGroupA] = useState("");
  const [newGroupB, setNewGroupB] = useState("");
  const [xCol, setXCol] = useState(numColumns[0]?.name || "");
  const [yCol, setYCol] = useState(numColumns[1]?.name || numColumns[0]?.name || "");
  const [degree, setDegree] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEscape(onClose, !busy);

  useEffect(() => {
    if (!groupCol) return;
    let active = true;
    const fallback = columns.find((c) => c.name === groupCol)?.top_values?.map((tv) => tv.value) || [];
    columnValues(dataset.id, groupCol, 200)
      .then((data) => {
        if (!active) return;
        const values = data.values.map((item) => item.value).filter((value) => value.trim().length > 0);
        setGroups(values);
        setGroupsTruncated(data.truncated);
        setPairs(values.length >= 2 ? [[values[0], values[1]]] : []);
        setNewGroupA(values[0] || "");
        setNewGroupB(values[1] || "");
      })
      .catch(() => {
        if (!active) return;
        setGroups(fallback);
        setPairs(fallback.length >= 2 ? [[fallback[0], fallback[1]]] : []);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id, groupCol]);

  const addPair = (a: string, b: string, current: [string, string][]) => {
    if (!a || !b || a === b) return current;
    const exists = current.some(([x, y]) => (x === a && y === b) || (x === b && y === a));
    return exists ? current : [...current, [a, b] as [string, string]];
  };

  const addAllPairs = () => {
    let next: [string, string][] = [];
    const subset = groups.slice(0, 8);
    for (let i = 0; i < subset.length; i += 1) {
      for (let j = i + 1; j < subset.length; j += 1) next = addPair(subset[i], subset[j], next);
    }
    setPairs(next);
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyStats = () =>
    run(async () => {
      const result = await annotateStats({
        dataset_id: dataset.id,
        code,
        group_col: groupCol,
        val_col: valCol,
        pairs,
        test_type: testType,
        correction_method: testType === "tukey" ? "none" : correction,
        pair_col: PAIRED.includes(testType) ? pairCol : undefined,
        preset,
      });
      onSuccess(result, "stats");
    });

  const applyRegression = () =>
    run(async () => {
      const result = await regressionPlot({ dataset_id: dataset.id, code, x_col: xCol, y_col: yCol, degree, preset });
      onSuccess(result, "regression");
    });

  const testOptions: { value: TestType; label: string }[] = [
    { value: "auto", label: zh ? "Welch t 检验（默认）" : "Welch's t-test" },
    { value: "mann-whitney", label: zh ? "Mann-Whitney U（非参数）" : "Mann-Whitney U" },
    { value: "paired-t", label: zh ? "配对 t 检验" : "Paired t-test" },
    { value: "wilcoxon", label: zh ? "Wilcoxon 符号秩（配对非参数）" : "Wilcoxon signed-rank" },
    { value: "tukey", label: zh ? "Tukey HSD 事后比较（多组）" : "Tukey HSD (post hoc)" },
  ];
  const needsPairs = PAIRED.includes(testType);
  const statsReady = groupCol && valCol && groups.length >= 2 && pairs.length > 0 && (!needsPairs || pairCol);

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-dialog stats-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? "⚡ 统计检验与回归" : "⚡ Statistics & regression"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="journal-tabs">
          <button type="button" className={`journal-tab ${tab === "stats" ? "active" : ""}`} onClick={() => setTab("stats")}>
            {zh ? "显著性标注" : "Significance"}
          </button>
          <button type="button" className={`journal-tab ${tab === "regression" ? "active" : ""}`} onClick={() => setTab("regression")}>
            {zh ? "回归拟合" : "Regression"}
          </button>
        </div>

        <div className="modal-body">
          {tab === "stats" ? (
            <>
              <p className="modal-desc">
                {zh
                  ? "计算组间检验并在图上方添加括号与星号（*** p<0.001, ** p<0.01, * p<0.05, ns）。星号使用校正后的 p 值。"
                  : "Runs the tests and adds brackets with stars above the plot (*** p<0.001 … ns), using corrected p-values."}
              </p>
              <div className="form-row">
                <div className="form-group">
                  <label>{zh ? "分组列 (X 轴分类)" : "Group column"}</label>
                  <select value={groupCol} onChange={(e) => setGroupCol(e.target.value)} disabled={busy}>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name} ({c.dtype}, {c.n_unique} {zh ? "类" : "levels"})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>{zh ? "数值列 (Y 轴)" : "Value column"}</label>
                  <select value={valCol} onChange={(e) => setValCol(e.target.value)} disabled={busy}>
                    {numColumns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>{zh ? "检验方法" : "Test"}</label>
                  <select value={testType} onChange={(e) => setTestType(e.target.value as TestType)} disabled={busy}>
                    {testOptions.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>{zh ? "多重比较校正" : "Multiple-comparison correction"}</label>
                  <select value={testType === "tukey" ? "none" : correction} onChange={(e) => setCorrection(e.target.value)} disabled={busy || testType === "tukey"}>
                    <option value="bonferroni">Bonferroni</option>
                    <option value="fdr_bh">{zh ? "Benjamini-Hochberg (FDR)" : "Benjamini-Hochberg (FDR)"}</option>
                    <option value="none">{zh ? "不校正" : "None"}</option>
                  </select>
                </div>
              </div>
              {testType === "tukey" && (
                <p className="setup-hint">{zh ? "Tukey HSD 的 p 值已对所有两两比较做过校正。" : "Tukey HSD p-values are already adjusted for all pairwise comparisons."}</p>
              )}
              {needsPairs && (
                <div className="form-group">
                  <label>{zh ? "配对 ID 列（如受试者编号）" : "Pairing ID column (e.g. subject)"}</label>
                  <select value={pairCol} onChange={(e) => setPairCol(e.target.value)} disabled={busy}>
                    <option value="">{zh ? "请选择…" : "Select…"}</option>
                    {columns.filter((c) => c.name !== groupCol && c.name !== valCol).map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="form-group">
                <label>
                  {zh ? "对比组对" : "Pairs to compare"}
                  {groupsTruncated && <small className="setup-hint"> {zh ? "（取值过多，只列出最常见的 200 个）" : "(showing the 200 most frequent values)"}</small>}
                </label>
                <div className="pair-chips">
                  {pairs.map(([a, b], idx) => (
                    <span key={`${a}-${b}`} className="pair-chip">
                      <strong>{a}</strong> vs <strong>{b}</strong>
                      <button type="button" onClick={() => setPairs(pairs.filter((_, i) => i !== idx))} disabled={busy}>×</button>
                    </span>
                  ))}
                  {pairs.length === 0 && <span className="empty-hint">{zh ? "请至少添加一组对比" : "Add at least one pair"}</span>}
                </div>
                {groups.length >= 2 && (
                  <div className="add-pair-row">
                    <select value={newGroupA} onChange={(e) => setNewGroupA(e.target.value)}>
                      {groups.map((g) => <option key={g} value={g}>{g}</option>)}
                    </select>
                    <span>vs</span>
                    <select value={newGroupB} onChange={(e) => setNewGroupB(e.target.value)}>
                      {groups.map((g) => <option key={g} value={g}>{g}</option>)}
                    </select>
                    <button
                      type="button"
                      className="btn secondary small"
                      onClick={() => setPairs(addPair(newGroupA, newGroupB, pairs))}
                      disabled={busy || !newGroupA || !newGroupB || newGroupA === newGroupB}
                    >
                      {zh ? "+ 添加" : "+ Add"}
                    </button>
                    <button type="button" className="btn secondary small" onClick={addAllPairs} disabled={busy}>
                      {zh ? "全部两两比较" : "All pairs"}
                    </button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              <p className="modal-desc">
                {zh
                  ? "用最小二乘法拟合 y 关于 x 的多项式，在当前图上画出拟合曲线并标注方程、R²（一阶时附斜率 p 值）。"
                  : "Least-squares polynomial fit of y on x, drawn on the current axes with its equation and R² (slope p-value for linear fits)."}
              </p>
              <div className="form-row">
                <div className="form-group">
                  <label>X</label>
                  <select value={xCol} onChange={(e) => setXCol(e.target.value)} disabled={busy}>
                    {numColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label>Y</label>
                  <select value={yCol} onChange={(e) => setYCol(e.target.value)} disabled={busy}>
                    {numColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="radio-pills">
                {[1, 2, 3].map((value) => (
                  <label key={value} className={`radio-pill ${degree === value ? "active" : ""}`}>
                    <input type="radio" checked={degree === value} onChange={() => setDegree(value)} />
                    {zh ? ["线性", "二次", "三次"][value - 1] : ["Linear", "Quadratic", "Cubic"][value - 1]}
                  </label>
                ))}
              </div>
            </>
          )}
          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>{zh ? "取消" : "Cancel"}</button>
          {tab === "stats" ? (
            <button className="btn" onClick={applyStats} disabled={busy || !statsReady}>
              {busy ? (zh ? "计算中…" : "Calculating…") : zh ? "计算并标注" : "Compute & annotate"}
            </button>
          ) : (
            <button className="btn" onClick={applyRegression} disabled={busy || !xCol || !yCol || xCol === yCol}>
              {busy ? (zh ? "拟合中…" : "Fitting…") : zh ? "拟合并标注" : "Fit & annotate"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
