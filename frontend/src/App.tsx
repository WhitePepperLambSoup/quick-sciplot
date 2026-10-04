import { useCallback, useEffect, useState } from "react";
import {
  applyParameter,
  combineDatasets,
  critiquePlot,
  editPlot,
  getConfig,
  generatePlot,
  listHistory,
  listPresets,
  deleteDataset,
  listDatasets,
  restoreRevision,
  runCode,
  uploadDatasets,
  interactiveAdjustPlot,
} from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { CodeWorkbench } from "./components/CodeWorkbench";
import { DataPanel } from "./components/DataPanel";
import { ComplianceModal } from "./components/ComplianceModal";
import { ComposerModal } from "./components/ComposerModal";
import { Header } from "./components/Header";
import { MimicModal } from "./components/MimicModal";
import { StatsModal } from "./components/StatsModal";
import type { Language } from "./components/ParameterInput";
import { PreviewCanvas } from "./components/PreviewCanvas";
import { SettingsDialog } from "./components/SettingsDialog";
import { ToastContainer, type ToastMessage } from "./components/Toast";
import type {
  ChatMessage,
  CodeParameter,
  DatasetInfo,
  LLMConfig,
  PlotResult,
  Preset,
  RevisionSummary,
  StatementCard,
} from "./types";

const FALLBACK_PRESETS: Preset[] = [
  { id: "default", name: "默认 Matplotlib", description: "Matplotlib 默认风格，适合快速预览。", source: "内置", source_url: "", category: "基础", local_available: false, has_fallback: true },
  { id: "science", name: "SciencePlots 科研", description: "简洁、细线、内向刻度，适合一般科研论文。", source: "SciencePlots", source_url: "", category: "论文", local_available: false, has_fallback: true },
  { id: "science-nature", name: "Nature 期刊", description: "Nature 论文常用的紧凑无衬线风格。", source: "SciencePlots", source_url: "", category: "期刊", local_available: false, has_fallback: true },
  { id: "science-ieee", name: "IEEE 期刊", description: "适合 IEEE 单栏论文的紧凑黑白友好风格。", source: "SciencePlots", source_url: "", category: "期刊", local_available: false, has_fallback: true },
  { id: "science-bright", name: "SciencePlots 色盲友好", description: "适合多系列数据的色盲友好配色。", source: "SciencePlots", source_url: "", category: "配色", local_available: false, has_fallback: true },
  { id: "lovely", name: "LovelyPlots 论文", description: "干净、可编辑，适合论文和学位论文排版。", source: "LovelyPlots", source_url: "", category: "论文", local_available: false, has_fallback: true },
  { id: "tueplots", name: "期刊尺寸（tueplots）", description: "按出版物尺寸和字体层级组织的基础风格。", source: "tueplots", source_url: "", category: "尺寸", local_available: false, has_fallback: true },
];

const DEFAULT_LLM_CONFIG: LLMConfig = {
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  mock: false,
  has_api_key: false,
  api_key_masked: "",
  auto_repair_attempts: 1,
  sandbox_timeout: 60,
  sandbox_mode: "docker",
  send_data_values: false,
};

export default function App() {
  const [language, setLanguage] = useState<Language>(() => {
    const stored = window.localStorage.getItem("quick-sciplot-language");
    return stored === "en" ? "en" : "zh";
  });
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [presets, setPresets] = useState<Preset[]>(FALLBACK_PRESETS);
  const [selectedPreset, setSelectedPreset] = useState("default");
  const [history, setHistory] = useState<RevisionSummary[]>([]);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(DEFAULT_LLM_CONFIG);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [mimicOpen, setMimicOpen] = useState(false);
  const [complianceOpen, setComplianceOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [result, setResult] = useState<PlotResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [editorCode, setEditorCode] = useState("");
  const [activeCard, setActiveCard] = useState<StatementCard | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const addToast = (type: "info" | "success" | "warning" | "error", message: string, title?: string) => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 7);
    setToasts((prev) => [...prev, { id, type, message, title }]);
  };

  // Must be stable: each toast's auto-dismiss timer depends on this callback, so a
  // new function on every render (e.g. every keystroke in the chat box) restarted
  // the timers and toasts never expired while the user was typing.
  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toggleLanguage = () => {
    const next = language === "zh" ? "en" : "zh";
    setLanguage(next);
    window.localStorage.setItem("quick-sciplot-language", next);
  };

  useEffect(() => {
    let disposed = false;
    // The packaged one-file backend unpacks itself on every launch and can take
    // well over 30 seconds on a busy machine, so keep retrying for a while.
    const startedAt = Date.now();
    const BACKEND_STARTUP_TIMEOUT_MS = 180_000;
    let timer: number | undefined;
    const loadBackendMetadata = async () => {
      try {
        const nextConfig = await getConfig();
        const [nextPresets, savedDatasets] = await Promise.all([
          listPresets(),
          listDatasets(),
        ]);
        if (disposed) return;
        if (nextPresets.length > 0) setPresets(nextPresets);
        setLlmConfig(nextConfig);
        if (savedDatasets && savedDatasets.length > 0) {
          setDatasets(savedDatasets);
          setDataset(savedDatasets[0]);
          setSelectedDatasetIds([savedDatasets[0].id]);
        }
      } catch {
        if (disposed) return;
        if (Date.now() - startedAt < BACKEND_STARTUP_TIMEOUT_MS) {
          timer = window.setTimeout(loadBackendMetadata, 1500);
        } else {
          addToast(
            "error",
            language === "zh"
              ? "无法连接本地后端服务，请重启应用后重试"
              : "Cannot reach the local backend; restart the app and try again",
          );
        }
      }
    };
    void loadBackendMetadata();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const handleDeleteDataset = async (id: string) => {
    try {
      await deleteDataset(id);
      const next = datasets.filter((d) => d.id !== id);
      setDatasets(next);
      setSelectedDatasetIds((prev) => prev.filter((x) => x !== id));
      if (dataset?.id === id) {
        const nextActive = next.length > 0 ? next[0] : null;
        setDataset(nextActive);
        setResult(null);
        setEditorCode("");
        setActiveCard(null);
      }
      addToast("info", language === "zh" ? "数据集已成功移除" : "Dataset removed");
    } catch (e) {
      addToast("error", String(e), language === "zh" ? "删除失败" : "Delete failed");
    }
  };

  useEffect(() => {
    const datasetId = dataset?.id;
    if (!datasetId) {
      setHistory([]);
      return;
    }
    listHistory(datasetId).then(setHistory).catch(() => setHistory([]));
  }, [dataset?.id]);

  const refreshHistory = async (datasetId: string) => {
    try {
      setHistory(await listHistory(datasetId));
    } catch {
      // 历史记录失败不阻塞绘图
    }
  };

  const handleUpload = async (files: File[]) => {
    if (files.length === 0) return;
    setBusy(true);
    try {
      const loaded = await uploadDatasets(files);
      const ds = loaded[0];
      setDatasets((current) => [...current, ...loaded]);
      setSelectedDatasetIds(loaded.map((item) => item.id));
      setDataset(ds);
      setResult(null);
      addToast(
        "success",
        language === "zh"
          ? `已成功载入 ${loaded.length} 个数据文件`
          : `Successfully loaded ${loaded.length} files`
      );
      setMessages([
        {
          role: "assistant",
          content:
            language === "zh"
              ? `已导入 ${loaded.length} 个数据文件，当前使用 “${ds.name || "未命名"}”：${ds.summary.shape.rows} 行 × ${ds.summary.shape.cols} 列。`
              : `Imported ${loaded.length} files. Active: "${ds.name || "Unnamed"}" (${ds.summary.shape.rows} rows × ${ds.summary.shape.cols} cols).`,
        },
      ]);
    } catch (e) {
      addToast("error", String(e), language === "zh" ? "导入失败" : "Import Failed");
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const combineSelected = async () => {
    if (selectedDatasetIds.length < 2 || busy) return;
    setBusy(true);
    try {
      const combined = await combineDatasets(selectedDatasetIds);
      setDatasets((current) => [...current, combined]);
      setSelectedDatasetIds([combined.id]);
      setDataset(combined);
      setResult(null);
      setEditorCode("");
      setActiveCard(null);
      addToast(
        "success",
        language === "zh" ? "多表已成功合并" : "Datasets combined successfully"
      );
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content:
            language === "zh"
              ? `已将 ${selectedDatasetIds.length} 个文件按行拼接，新增来源列 source_file。`
              : `Combined ${selectedDatasetIds.length} files by rows with source_file column.`,
        },
      ]);
    } catch (error) {
      addToast("error", String(error));
      setMessages((m) => [...m, { role: "assistant", content: String(error), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !dataset || busy) return;
    setInput("");
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const res = result
        ? await editPlot(dataset.id, result.code, text, selectedPreset, nextMessages)
        : await generatePlot(dataset.id, text, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      if (res.run.success) {
        addToast(
          "success",
          language === "zh" ? "图表渲染完成 ✓" : "Plot rendered successfully ✓"
        );
      } else {
        addToast(
          "error",
          language === "zh" ? "代码执行错误，请查看控制台输出" : "Execution failed, check stderr"
        );
      }
      setMessages((m) => [
        ...m,
        res.run.success
          ? {
              role: "assistant",
              content: res.repair_attempts
                ? language === "zh"
                  ? `图已生成，自动修复 ${res.repair_attempts} 次 ✓`
                  : `Plot generated with ${res.repair_attempts} auto-repair(s) ✓`
                : language === "zh"
                ? "图已生成 ✓"
                : "Plot generated ✓",
            }
          : {
              role: "assistant",
              content: (language === "zh" ? "生成失败：" : "Failed: ") + (res.run.stderr || "未知错误"),
              error: true,
            },
      ]);
    } catch (e) {
      addToast("error", String(e));
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  }, [input, dataset, busy, result, selectedPreset, messages, language]);

  const runEditor = async () => {
    if (!dataset) return;
    setBusy(true);
    try {
      const res = await runCode(dataset.id, editorCode, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      if (res.run.success) {
        addToast("success", language === "zh" ? "代码已重跑渲染 ✓" : "Code re-rendered ✓");
      } else {
        addToast("error", language === "zh" ? "运行报错" : "Execution error");
      }
      setMessages((m) => [
        ...m,
        res.run.success
          ? { role: "assistant", content: language === "zh" ? "代码已重新执行渲染 ✓" : "Code re-rendered successfully ✓" }
          : { role: "assistant", content: (language === "zh" ? "运行失败：" : "Run error: ") + (res.run.stderr || "未知错误"), error: true },
      ]);
    } catch (e) {
      addToast("error", String(e));
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const applyParameterChange = async (parameter: CodeParameter, value: string) => {
    if (!dataset || !result || busy) return;
    setBusy(true);
    try {
      const res = await applyParameter(dataset.id, result.code, parameter, value, selectedPreset);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      setActiveCard(
        res.statements.find(
          (statement) => statement.start <= parameter.start_line && statement.end >= parameter.start_line,
        ) ?? null,
      );
      addToast("info", language === "zh" ? `已应用“${parameter.label}”` : `Applied "${parameter.name}"`);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: language === "zh" ? `已应用“${parameter.label}”并重新渲染 ✓` : `Applied "${parameter.name}" and re-rendered ✓`,
        },
      ]);
    } catch (e) {
      addToast("error", String(e));
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revision: RevisionSummary) => {
    if (!dataset || busy || !revision.success) return;
    setBusy(true);
    try {
      const res = await restoreRevision(revision.id);
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      setActiveCard(null);
      await refreshHistory(dataset.id);
      addToast("info", language === "zh" ? "已恢复历史版本" : "Version restored");
      setMessages((m) => [
        ...m,
        { role: "assistant", content: language === "zh" ? "已恢复历史版本并生成新版本 ✓" : "Version restored as new revision ✓" },
      ]);
    } catch (e) {
      addToast("error", String(e));
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const handleRunCritic = async () => {
    if (!result?.revision_id || busy) return;
    setBusy(true);
    try {
      const report = await critiquePlot(result.revision_id);
      const advice = report.suggestions.map((s) => `• ${s}`).join("\n");
      const summaryMsg =
        language === "zh"
          ? `【🔍 视觉排版体检报告】\n综合排版评分：${report.score}/100\n${advice}`
          : `【🔍 Visual Critique Report】\nLayout Score: ${report.score}/100\n${advice}`;
      addToast("info", language === "zh" ? `体检得分：${report.score}/100` : `Critique score: ${report.score}/100`);
      setMessages((m) => [...m, { role: "assistant", content: summaryMsg }]);
      if (report.repair_prompt) {
        setInput(report.repair_prompt);
      }
    } catch (e) {
      addToast("error", String(e));
      setMessages((m) => [...m, { role: "assistant", content: String(e), error: true }]);
    } finally {
      setBusy(false);
    }
  };

  const handleInteractiveAdjust = async (action: string, params: Record<string, unknown>) => {
    if (!dataset || !result || busy) return;
    setBusy(true);
    try {
      const res = await interactiveAdjustPlot({
        dataset_id: dataset.id,
        code: result.code,
        action,
        params,
        preset: selectedPreset,
      });
      setResult(res);
      setSelectedPreset(res.preset || selectedPreset);
      setEditorCode(res.code);
      void refreshHistory(dataset.id);
      addToast(
        "success",
        language === "zh"
          ? "🎯 交互修正已应用，绘图代码已同步更新！"
          : "🎯 Adjustment applied & code updated!"
      );
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content:
            language === "zh"
              ? `🎯 已完成画布可视化调整（${action}），代码已同步更新。`
              : `🎯 Visual adjustment applied (${action}), code synchronized.`,
        },
      ]);
    } catch (e) {
      addToast("error", String(e), language === "zh" ? "修正失败" : "Adjustment failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <Header
        language={language}
        llmConfig={llmConfig}
        busy={busy}
        hasDataset={!!dataset}
        onToggleLanguage={toggleLanguage}
        onOpenSettings={() => setSettingsOpen(true)}
        onUploadFiles={(files) => void handleUpload(files)}
        onOpenMimic={() => setMimicOpen(true)}
        onOpenComposer={() => setComposerOpen(true)}
      />

      <main className="layout">
        <DataPanel
          language={language}
          dataset={dataset}
          datasets={datasets}
          selectedDatasetIds={selectedDatasetIds}
          presets={presets}
          selectedPreset={selectedPreset}
          history={history}
          activeRevisionId={result?.revision_id}
          busy={busy}
          onSelectDataset={(item) => {
            setDataset(item);
            setResult(null);
            setEditorCode("");
            setActiveCard(null);
            setMessages([
              {
                role: "assistant",
                content:
                  language === "zh"
                    ? `已切换至 “${item.name || "未命名"}”：${item.summary.shape.rows} 行 × ${item.summary.shape.cols} 列。`
                    : `Switched to "${item.name || "Unnamed"}": ${item.summary.shape.rows} rows × ${item.summary.shape.cols} cols.`,
              },
            ]);
          }}
          onToggleDatasetSelect={(id, checked) => {
            setSelectedDatasetIds((current) => (checked ? [...current, id] : current.filter((x) => x !== id)));
          }}
          onCombineSelected={() => void combineSelected()}
          onSelectPreset={setSelectedPreset}
          onRestoreRevision={(rev) => void restore(rev)}
          onDeleteDataset={(id) => void handleDeleteDataset(id)}
        />

        <PreviewCanvas
          language={language}
          result={result}
          busy={busy}
          onRunCritic={handleRunCritic}
          onOpenStatsModal={() => setStatsOpen(true)}
          onOpenComplianceModal={() => setComplianceOpen(true)}
          onInteractiveAdjust={handleInteractiveAdjust}
        />

        <ChatPanel
          language={language}
          dataset={dataset}
          messages={messages}
          input={input}
          busy={busy}
          disabled={!dataset}
          onChangeInput={setInput}
          onSend={send}
        />
      </main>

      {result && (
        <CodeWorkbench
          language={language}
          result={result}
          editorCode={editorCode}
          activeCard={activeCard}
          busy={busy}
          onChangeEditorCode={setEditorCode}
          onSelectCard={(card) => {
            setActiveCard(card);
          }}
          onApplyParameter={applyParameterChange}
          onRunEditor={runEditor}
          onCopyCode={(_code, ok) =>
            ok
              ? addToast("info", language === "zh" ? "代码已复制到剪贴板 ✓" : "Code copied to clipboard ✓")
              : addToast("error", language === "zh" ? "复制失败，请在源码框中手动选择复制" : "Copy failed; select the code manually")
          }
        />
      )}

      {settingsOpen && (
        <SettingsDialog
          config={llmConfig}
          onClose={() => setSettingsOpen(false)}
          onSaved={(newCfg) => {
            setLlmConfig(newCfg);
            addToast("success", language === "zh" ? "设置已成功保存" : "Settings saved");
          }}
          language={language}
        />
      )}

      {statsOpen && dataset && result && (
        <StatsModal
          language={language}
          dataset={dataset}
          code={result.code}
          onClose={() => setStatsOpen(false)}
          onSuccess={(res) => {
            setResult(res);
            setEditorCode(res.code);
            void refreshHistory(dataset.id);
            addToast(
              "success",
              language === "zh" ? "显著性标尺与星号标注已成功注入！" : "Stat brackets added!"
            );
            setMessages((m) => [
              ...m,
              {
                role: "assistant",
                content:
                  language === "zh"
                    ? "⚡ 统计显著性计算完成，已注入标准连线标尺与显著性星号！"
                    : "⚡ Statistical significance computed and brackets injected!",
              },
            ]);
          }}
        />
      )}

      {composerOpen && dataset && (
        <ComposerModal
          language={language}
          dataset={dataset}
          currentCode={result?.code || ""}
          history={history}
          preset={selectedPreset}
          onClose={() => setComposerOpen(false)}
          onSuccess={(res) => {
            setResult(res);
            setEditorCode(res.code);
            void refreshHistory(dataset.id);
            addToast(
              "success",
              language === "zh" ? "组合大图编排完成！" : "Panels composed!"
            );
            setMessages((m) => [
              ...m,
              {
                role: "assistant",
                content:
                  language === "zh"
                    ? "📊 组合大图编排完成，已生成出版级多子图！"
                    : "📊 Multi-panel figure composed successfully!",
              },
            ]);
          }}
        />
      )}

      {mimicOpen && dataset && (
        <MimicModal
          language={language}
          dataset={dataset}
          preset={selectedPreset}
          onClose={() => setMimicOpen(false)}
          onSuccess={(res) => {
            setResult(res);
            setEditorCode(res.code);
            void refreshHistory(dataset.id);
            addToast(
              "success",
              language === "zh" ? "论文图版式复刻完成！" : "Paper figure replicated!"
            );
            setMessages((m) => [
              ...m,
              {
                role: "assistant",
                content:
                  language === "zh"
                    ? "🎨 论文图视觉版式逆向复刻完成！"
                    : "🎨 Paper figure style replicated successfully!",
              },
            ]);
          }}
        />
      )}

      {complianceOpen && result?.revision_id && (
        <ComplianceModal
          language={language}
          revisionId={result.revision_id}
          onClose={() => setComplianceOpen(false)}
          onApplyPrompt={(prompt) => {
            setInput(prompt);
            addToast("info", language === "zh" ? "修复建议已填入对话框" : "Prompt applied to chat");
          }}
        />
      )}

      {/* Global Toast Container */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
