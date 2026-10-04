import { useRef, useState } from "react";
import { mimicPlot } from "../api";
import type { DatasetInfo, PlotResult } from "../types";
import type { Language } from "./ParameterInput";

interface MimicModalProps {
  language: Language;
  dataset: DatasetInfo;
  preset?: string;
  onClose: () => void;
  onSuccess: (result: PlotResult) => void;
}

const TEMPLATE_SUGGESTIONS = [
  {
    title_zh: "Nature 双 Y 轴对照折线图",
    title_en: "Nature Dual-Axis Curve",
    desc: "双 Y 轴设计，主轴为实线+圆点，次轴为虚线+方块，内向刻度，合并右上角图例，纯学术无衬线字体。",
  },
  {
    title_zh: "Cell / Science 云雨图 (Raincloud)",
    title_en: "Cell Raincloud / Violin",
    desc: "小提琴轮廓指示数据整体密度，内部嵌套细窄白色箱线图，右侧叠加抖动散点 (Jitter Stripplot)，无顶部与右侧边框。",
  },
  {
    title_zh: "顶刊相关性三角热图",
    title_en: "Correlation Triangular Heatmap",
    desc: "下三角相关系数热图，单元格标注两两 Pearson r 值与显著性星号，右侧带渐变色条 (Colorbar)，冷暖配色方案。",
  },
];

export function MimicModal({ language, dataset, preset, onClose, onSuccess }: MimicModalProps) {
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [description, setDescription] = useState(
    language === "zh"
      ? "复刻参考论文图的排版版式：双轴对照，左侧与右侧数据刻度内向，无多余网格线。"
      : "Mimic the paper figure layout: dual-axis comparison, inward ticks, minimal grid lines."
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (file?: File) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const res = e.target?.result;
      if (typeof res === "string") {
        setImageB64(res);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleMimic = async () => {
    if (!description.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await mimicPlot({
        dataset_id: dataset.id,
        reference_description: description,
        reference_image_b64: imageB64 || undefined,
        preset,
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
      <div className="modal-dialog mimic-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{language === "zh" ? "🎨 顶刊论文图“以图生图”复刻 (Paper Mimic)" : "🎨 Paper Figure Mimic"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">
            {language === "zh"
              ? "上传 Nature / Science / Cell 等论文插图截图，结合您的数据集结构，自动逆向解构其图表排版、配色与字体风格并生成复刻代码。"
              : "Upload a screenshot of a paper figure. We'll reverse-engineer its layout, color palette, and styling for your dataset."}
          </p>

          <div className="form-group">
            <label>{language === "zh" ? "参考论文图截图 (可选)" : "Reference Paper Screenshot (Optional)"}</label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={(e) => handleFileChange(e.target.files?.[0])}
            />
            {imageB64 ? (
              <div className="image-preview-box">
                <img src={imageB64} alt="Reference Preview" className="reference-thumb" />
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => {
                    setImageB64(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                  disabled={busy}
                >
                  {language === "zh" ? "移除图片" : "Remove"}
                </button>
              </div>
            ) : (
              <div
                className="dropzone-box"
                onClick={() => fileInputRef.current?.click()}
              >
                <span className="dropzone-icon">📷</span>
                <span className="dropzone-text">
                  {language === "zh"
                    ? "点击上传参考论文图截图 (PNG / JPG)"
                    : "Click to upload paper figure screenshot (PNG / JPG)"}
                </span>
              </div>
            )}
          </div>

          <div className="form-group">
            <label>{language === "zh" ? "快速填充常用顶刊复刻模板" : "Quick Presets"}</label>
            <div className="template-cards">
              {TEMPLATE_SUGGESTIONS.map((tpl, i) => (
                <div
                  key={i}
                  className="template-card"
                  onClick={() => setDescription(tpl.desc)}
                >
                  <div className="tpl-title">{language === "zh" ? tpl.title_zh : tpl.title_en}</div>
                  <div className="tpl-desc">{tpl.desc}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label>{language === "zh" ? "版式复刻要求与细节说明" : "Figure Mimic Details & Requirements"}</label>
            <textarea
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={
                language === "zh"
                  ? "输入您希望复刻的具体视觉特征（例如：双 Y 轴、特定色系、显著性标记、小提琴图等）..."
                  : "Specify visual features (e.g. dual-axis, colors, violin density)..."
              }
              disabled={busy}
            />
          </div>

          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>
            {language === "zh" ? "取消" : "Cancel"}
          </button>
          <button className="btn" onClick={handleMimic} disabled={busy || !description.trim()}>
            {busy
              ? (language === "zh" ? "逆向解构复刻中..." : "Reverse engineering...")
              : (language === "zh" ? "开始论文级复刻" : "Start Mimicking")}
          </button>
        </div>
      </div>
    </div>
  );
}
