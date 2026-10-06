import { useEffect, useMemo, useState } from "react";
import { listTemplates, plotTemplate } from "../api";
import { isNumericColumn } from "../columns";
import type { DatasetInfo, PlotResult, TemplateInfo, TemplateParam } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface TemplateGalleryProps {
  language: Language;
  dataset: DatasetInfo;
  preset?: string;
  onClose: () => void;
  onSuccess: (result: PlotResult, templateName: string) => void;
}

const ICONS: Record<string, string> = {
  volcano: "🌋",
  km_survival: "📉",
  pca: "🧭",
  clustermap: "🧩",
  dose_response: "💊",
  correlation: "🔗",
  bar_points: "📊",
};

/** Pick a sensible default column for a parameter from its name. */
function guessColumn(param: TemplateParam, columns: string[], numeric: string[]): string {
  const hints: Record<string, string[]> = {
    fc_col: ["log2fc", "logfc", "fc", "fold"],
    p_col: ["padj", "pvalue", "p_value", "pval", "p."],
    label_col: ["gene", "name", "symbol", "id"],
    time_col: ["time", "day", "month", "survival"],
    event_col: ["event", "status", "dead", "death"],
    group_col: ["group", "treatment", "condition", "arm", "type"],
    dose_col: ["dose", "conc", "concentration"],
    response_col: ["response", "inhibition", "viability", "signal"],
    value_col: ["value", "score", "level", "expression"],
  };
  const pool = param.kind === "numeric" ? numeric : columns;
  for (const hint of hints[param.name] || []) {
    const match = pool.find((column) => column.toLowerCase().includes(hint));
    if (match) return match;
  }
  return param.required ? pool[0] || "" : "";
}

export function TemplateGallery({ language, dataset, preset, onClose, onSuccess }: TemplateGalleryProps) {
  const zh = language === "zh";
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [selected, setSelected] = useState<TemplateInfo | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEscape(onClose, !busy);

  const columns = useMemo(() => dataset.summary.columns.map((column) => column.name), [dataset]);
  const numeric = useMemo(() => dataset.summary.columns.filter(isNumericColumn).map((column) => column.name), [dataset]);

  useEffect(() => {
    listTemplates().then(setTemplates).catch((err) => setError(String(err)));
  }, []);

  const choose = (template: TemplateInfo) => {
    setSelected(template);
    setError(null);
    const defaults: Record<string, unknown> = {};
    for (const param of template.params) {
      if (param.kind === "column" || param.kind === "numeric") defaults[param.name] = guessColumn(param, columns, numeric);
      else if (param.kind === "numeric_multi") defaults[param.name] = [];
      else defaults[param.name] = param.default ?? "";
    }
    setValues(defaults);
  };

  const submit = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const params: Record<string, unknown> = {};
      for (const param of selected.params) {
        const value = values[param.name];
        if (value === "" || value === undefined || (Array.isArray(value) && value.length === 0)) continue;
        params[param.name] = param.kind === "number" ? Number(value) : value;
      }
      const result = await plotTemplate({ dataset_id: dataset.id, template_id: selected.id, params, preset });
      onSuccess(result, zh ? selected.name_zh : selected.name_en);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const renderParam = (param: TemplateParam) => {
    const label = zh ? param.label_zh : param.label_en;
    const value = values[param.name];
    if (param.kind === "column" || param.kind === "numeric") {
      const pool = param.kind === "numeric" ? numeric : columns;
      return (
        <div className="form-group" key={param.name}>
          <label>{label}</label>
          <select value={String(value ?? "")} onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}>
            {!param.required && <option value="">{zh ? "（不使用）" : "(none)"}</option>}
            {pool.map((column) => <option key={column}>{column}</option>)}
          </select>
        </div>
      );
    }
    if (param.kind === "numeric_multi") {
      const chosen = (value as string[]) || [];
      return (
        <div className="form-group" key={param.name}>
          <label>{label}</label>
          <div className="column-checklist">
            {numeric.map((column) => (
              <label key={column} className={`column-chip ${chosen.includes(column) ? "active" : ""}`}>
                <input
                  type="checkbox"
                  checked={chosen.includes(column)}
                  onChange={(e) =>
                    setValues({ ...values, [param.name]: e.target.checked ? [...chosen, column] : chosen.filter((c) => c !== column) })
                  }
                />
                {column}
              </label>
            ))}
          </div>
        </div>
      );
    }
    if (param.kind === "choice") {
      return (
        <div className="form-group" key={param.name}>
          <label>{label}</label>
          <select value={String(value ?? "")} onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}>
            {param.options.map((option) => <option key={option}>{option}</option>)}
          </select>
        </div>
      );
    }
    return (
      <div className="form-group" key={param.name}>
        <label>{label}</label>
        <input
          type="number"
          step="any"
          value={String(value ?? "")}
          min={param.minimum ?? undefined}
          max={param.maximum ?? undefined}
          onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}
        />
      </div>
    );
  };

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-dialog template-gallery" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? "🧪 科研图模板" : "🧪 Scientific figure templates"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>
        <div className="modal-body">
          <p className="modal-desc">
            {zh
              ? "模板用固定的代码生成图表，不调用 AI 模型，结果稳定可复现；生成后仍可继续用对话或代码修改。"
              : "Templates produce deterministic plotting code without the AI model; you can keep refining the result afterwards."}
          </p>
          <div className="template-grid">
            {templates.map((template) => (
              <button
                key={template.id}
                type="button"
                className={`template-tile ${selected?.id === template.id ? "active" : ""}`}
                onClick={() => choose(template)}
                disabled={busy}
              >
                <span className="template-icon">{ICONS[template.id] || "📈"}</span>
                <strong>{zh ? template.name_zh : template.name_en}</strong>
                <small>{zh ? template.description_zh : template.description_en}</small>
              </button>
            ))}
          </div>
          {selected && <div className="template-params">{selected.params.map(renderParam)}</div>}
          {error && <div className="error-alert">{error}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>{zh ? "取消" : "Cancel"}</button>
          <button className="btn" onClick={submit} disabled={busy || !selected}>
            {busy ? (zh ? "生成中…" : "Rendering…") : zh ? "生成图表" : "Create figure"}
          </button>
        </div>
      </div>
    </div>
  );
}
