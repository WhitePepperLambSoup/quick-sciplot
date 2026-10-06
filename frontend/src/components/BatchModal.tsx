import { useEffect, useState } from "react";
import { batchPlot, exportRevisionsZip, fetchThumbnail } from "../api";
import type { BatchItem, DatasetInfo } from "../types";
import { saveBlob, useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface BatchModalProps {
  language: Language;
  datasets: DatasetInfo[];
  currentDatasetId?: string;
  code: string;
  preset?: string;
  onClose: () => void;
  onDone?: () => void;
}

export function BatchModal({ language, datasets, currentDatasetId, code, preset, onClose, onDone }: BatchModalProps) {
  const zh = language === "zh";
  const [selected, setSelected] = useState<string[]>(datasets.filter((d) => d.id !== currentDatasetId).map((d) => d.id).slice(0, 20));
  const [items, setItems] = useState<BatchItem[] | null>(null);
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const [format, setFormat] = useState("png");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEscape(onClose, !busy);

  useEffect(() => {
    if (!items) return;
    let active = true;
    const urls: string[] = [];
    for (const item of items) {
      if (!item.success || !item.revision_id || !item.export_formats?.includes("png")) continue;
      fetchThumbnail(item.revision_id)
        .then((url) => {
          urls.push(url);
          if (active) setThumbnails((current) => ({ ...current, [item.revision_id as string]: url }));
        })
        .catch(() => undefined);
    }
    return () => {
      active = false;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [items]);

  const run = async () => {
    setBusy(true);
    setError(null);
    setItems(null);
    try {
      const response = await batchPlot({ code, dataset_ids: selected, preset });
      setItems(response.items);
      onDone?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!items) return;
    setBusy(true);
    setError(null);
    try {
      const ids = items.filter((item) => item.success && item.revision_id).map((item) => item.revision_id as string);
      saveBlob(await exportRevisionsZip(ids, format), `quick-sciplot-batch-${format}.zip`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const succeeded = items?.filter((item) => item.success).length ?? 0;

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-dialog batch-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? "🗃️ 批量出图" : "🗃️ Batch plotting"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>
        <div className="modal-body">
          <p className="modal-desc">
            {zh
              ? "把当前这段绘图代码原样套用到所选的每个数据集上（列名需要一致），每个数据集各生成一个版本。"
              : "Run the current plotting code unchanged on each selected dataset (column names must match); each dataset gets its own revision."}
          </p>
          {!items && (
            <div className="batch-list">
              {datasets.map((dataset) => (
                <label key={dataset.id} className="batch-row">
                  <input
                    type="checkbox"
                    checked={selected.includes(dataset.id)}
                    disabled={busy || (!selected.includes(dataset.id) && selected.length >= 20)}
                    onChange={(e) =>
                      setSelected((current) => (e.target.checked ? [...current, dataset.id] : current.filter((id) => id !== dataset.id)))
                    }
                  />
                  <span className="batch-name">{dataset.name || dataset.id}</span>
                  <span className="dataset-file-badge">
                    {dataset.summary.shape.rows} × {dataset.summary.shape.cols}
                  </span>
                  {dataset.id === currentDatasetId && <span className="setup-tag">{zh ? "当前" : "Current"}</span>}
                </label>
              ))}
            </div>
          )}
          {busy && !items && <div className="compliance-loading">{zh ? `正在为 ${selected.length} 个数据集出图…` : `Plotting ${selected.length} datasets…`}</div>}
          {items && (
            <>
              <div className={`setup-banner ${succeeded === items.length ? "ready" : "blocked"}`}>
                {zh ? `完成：${succeeded} / ${items.length} 个成功` : `Done: ${succeeded} / ${items.length} succeeded`}
              </div>
              <div className="batch-results">
                {items.map((item) => (
                  <div key={item.dataset_id} className={`batch-result ${item.success ? "ok" : "failed"}`}>
                    <div className="batch-thumb">
                      {item.revision_id && thumbnails[item.revision_id] ? (
                        <img src={thumbnails[item.revision_id]} alt={item.name || item.dataset_id} />
                      ) : (
                        <span>{item.success ? "…" : "✕"}</span>
                      )}
                    </div>
                    <div className="batch-caption">
                      <strong>{item.name || item.dataset_id}</strong>
                      {!item.success && <small>{(item.error || item.stderr || "").split("\n").filter(Boolean).slice(-1)[0]}</small>}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
          {error && <div className="error-alert">{error}</div>}
        </div>
        <div className="modal-footer">
          {items ? (
            <>
              <select className="batch-format" value={format} onChange={(e) => setFormat(e.target.value)} disabled={busy}>
                {["png", "svg", "pdf", "eps"].map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
              </select>
              <button className="btn secondary" onClick={download} disabled={busy || succeeded === 0}>
                {zh ? "打包下载" : "Download zip"}
              </button>
              <button className="btn" onClick={onClose} disabled={busy}>{zh ? "完成" : "Done"}</button>
            </>
          ) : (
            <>
              <button className="btn secondary" onClick={onClose} disabled={busy}>{zh ? "取消" : "Cancel"}</button>
              <button className="btn" onClick={run} disabled={busy || selected.length === 0 || !code.trim()}>
                {busy ? (zh ? "出图中…" : "Plotting…") : zh ? `开始批量出图（${selected.length}）` : `Run on ${selected.length}`}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
