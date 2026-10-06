import { useEffect, useMemo, useState } from "react";
import { fetchThumbnail, getRevisionDetail } from "../api";
import { operationInfo } from "../operations";
import type { RevisionDetail } from "../types";
import { diffLines, useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface RevisionDiffModalProps {
  language: Language;
  olderId: string;
  newerId: string;
  onClose: () => void;
}

function RevisionCard({ language, revision, image }: { language: Language; revision: RevisionDetail | null; image?: string }) {
  return (
    <div className="diff-card">
      <div className="diff-thumb">
        {image ? <img src={image} alt={revision?.label || revision?.id} /> : <span>{revision?.success === false ? "✕" : "…"}</span>}
      </div>
      {revision && (
        <div className="diff-meta">
          <strong>
            {operationInfo(revision.operation, language).icon} {revision.label || operationInfo(revision.operation, language).label}
          </strong>
          <small>
            {revision.created_at} · {revision.preset}
            {revision.starred ? " · ★" : ""}
          </small>
          {!revision.success && <small className="diff-failed">{language === "zh" ? "失败版本" : "Failed revision"}</small>}
        </div>
      )}
    </div>
  );
}

export function RevisionDiffModal({ language, olderId, newerId, onClose }: RevisionDiffModalProps) {
  const zh = language === "zh";
  const [older, setOlder] = useState<RevisionDetail | null>(null);
  const [newer, setNewer] = useState<RevisionDetail | null>(null);
  const [images, setImages] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  useEscape(onClose);

  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    Promise.all([getRevisionDetail(olderId), getRevisionDetail(newerId)])
      .then(([a, b]) => {
        if (!active) return;
        setOlder(a);
        setNewer(b);
        for (const revision of [a, b]) {
          if (!revision.success) continue;
          fetchThumbnail(revision.id)
            .then((url) => {
              urls.push(url);
              if (active) setImages((current) => ({ ...current, [revision.id]: url }));
            })
            .catch(() => undefined);
        }
      })
      .catch((err) => active && setError(String(err)));
    return () => {
      active = false;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [olderId, newerId]);

  const diff = useMemo(() => (older && newer ? diffLines(older.code, newer.code) : []), [older, newer]);
  const added = diff.filter((line) => line.kind === "added").length;
  const removed = diff.filter((line) => line.kind === "removed").length;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog diff-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? "🔍 版本对比" : "🔍 Compare revisions"}</h3>
          <button className="btn-icon" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="diff-cards">
            <RevisionCard language={language} revision={older} image={older ? images[older.id] : undefined} />
            <span className="diff-arrow">→</span>
            <RevisionCard language={language} revision={newer} image={newer ? images[newer.id] : undefined} />
          </div>
          {older && newer && (
            <div className="diff-summary">
              {zh ? `代码变化：+${added} 行，−${removed} 行` : `Code changes: +${added}, −${removed} lines`}
            </div>
          )}
          <pre className="diff-code">
            {diff.map((line, index) => (
              <div key={index} className={`diff-line ${line.kind}`}>
                <span className="diff-sign">{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>
                {line.text || " "}
              </div>
            ))}
          </pre>
          {error && <div className="error-alert">{error}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose}>{zh ? "关闭" : "Close"}</button>
        </div>
      </div>
    </div>
  );
}
