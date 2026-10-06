import type { Language } from "./components/ParameterInput";

export const OPERATION_LABELS: Record<string, { zh: string; en: string; icon: string }> = {
  generate: { zh: "初始生成", en: "Generated", icon: "✨" },
  edit: { zh: "对话调整", en: "Edited", icon: "💬" },
  parameter: { zh: "参数微调", en: "Param Tweak", icon: "⚙️" },
  run: { zh: "代码重跑", en: "Code Run", icon: "▶️" },
  restore: { zh: "版本恢复", en: "Restored", icon: "⏪" },
  stats: { zh: "统计标注", en: "Stat Brackets", icon: "⚡" },
  regression: { zh: "回归拟合", en: "Regression", icon: "📈" },
  compose: { zh: "多图拼版", en: "Composed", icon: "📊" },
  mimic: { zh: "论文图复刻", en: "Mimic", icon: "🎨" },
  interactive: { zh: "交互修正", en: "Interactive Fix", icon: "🎯" },
  template: { zh: "科研模板", en: "Template", icon: "🧪" },
  "fit-journal": { zh: "期刊版面", en: "Journal Fit", icon: "📐" },
  batch: { zh: "批量出图", en: "Batch", icon: "🗃️" },
};

export function operationInfo(operation: string, language: Language): { label: string; icon: string } {
  const info = OPERATION_LABELS[operation];
  return info ? { label: info[language], icon: info.icon } : { label: operation, icon: "📌" };
}
