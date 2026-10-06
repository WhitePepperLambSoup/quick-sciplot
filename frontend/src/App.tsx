import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyParameter,
  combineDatasets,
  critiquePlot,
  deleteDataset,
  getConfig,
  getSystemStatus,
  interactiveAdjustPlot,
  listDatasets,
  listHistory,
  listPresets,
  restoreRevision,
  runCode,
  streamPlot,
  updateLLMConfig,
  updateRevision,
  uploadDatasets,
} from "./api";
import { BatchModal } from "./components/BatchModal";
import { ChatPanel, type StreamState } from "./components/ChatPanel";
import { CodeWorkbench } from "./components/CodeWorkbench";
import { ComplianceModal } from "./components/ComplianceModal";
import { ComposerModal } from "./components/ComposerModal";
import { DataPanel } from "./components/DataPanel";
import { DataWorkbench } from "./components/DataWorkbench";
import { Header, type BackendState } from "./components/Header";
import { MimicModal } from "./components/MimicModal";
import type { Language } from "./components/ParameterInput";
import { PreviewCanvas } from "./components/PreviewCanvas";
import { RevisionDiffModal } from "./components/RevisionDiffModal";
import { SettingsDialog } from "./components/SettingsDialog";
import { SetupWizard } from "./components/SetupWizard";
import { StatsModal } from "./components/StatsModal";
import { TemplateGallery } from "./components/TemplateGallery";
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
  SystemStatus,
} from "./types";
import { checkForUpdate } from "./updater";

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

const IMPORT_EXTENSIONS = [".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json"];
// The packaged backend may need a while on first launch (antivirus scans etc.).
const BACKEND_STARTUP_TIMEOUT_MS = 180_000;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const [language, setLanguage] = useState<Language>(() => {
    try {
      return window.localStorage.getItem("quick-sciplot-language") === "en" ? "en" : "zh";
    } catch {
      return "zh";
    }
  });
  const zh = language === "zh";
  const [dataset, setDataset] = useState<DatasetInfo | null>(null);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [presets, setPresets] = useState<Preset[]>(FALLBACK_PRESETS);
  const [selectedPreset, setSelectedPreset] = useState("default");
  const [history, setHistory] = useState<RevisionSummary[]>([]);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(DEFAULT_LLM_CONFIG);
  const [backendState, setBackendState] = useState<BackendState>("connecting");
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [mimicOpen, setMimicOpen] = useState(false);
  const [complianceOpen, setComplianceOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [workbenchDataset, setWorkbenchDataset] = useState<DatasetInfo | null>(null);
  const [diffPair, setDiffPair] = useState<{ older: string; newer: string } | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [result, setResult] = useState<PlotResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [editorCode, setEditorCode] = useState("");
  const [activeCard, setActiveCard] = useState<StatementCard | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const addToast = useCallback((type: ToastMessage["type"], message: string, title?: string, extra?: Partial<ToastMessage>) => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 7);
    setToasts((prev) => [...prev, { id, type, message, title, ...extra }]);
  }, []);

  // Must be stable: each toast's auto-dismiss timer depends on this callback, so a
  // new function on every render (e.g. every keystroke in the chat box) restarted
  // the timers and toasts never expired while the user was typing.
  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const pushMessage = useCallback((message: ChatMessage) => setMessages((m) => [...m, message]), []);

  const toggleLanguage = () => {
    const next = language === "zh" ? "en" : "zh";
    setLanguage(next);
    try {
      window.localStorage.setItem("quick-sciplot-language", next);
    } catch {
      // Storage may be unavailable; the choice still applies to this session.
    }
  };

  const refreshSystemStatus = useCallback(async () => {
    try {
      const status = await getSystemStatus();
      setSystemStatus(status);
      return status;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    const startedAt = Date.now();
    let timer: number | undefined;
    const loadBackendMetadata = async () => {
      try {
        const nextConfig = await getConfig();
        const [nextPresets, savedDatasets] = await Promise.all([listPresets(), listDatasets()]);
        if (disposed) return;
        setBackendState("ready");
        if (nextPresets.length > 0) setPresets(nextPresets);
        setLlmConfig(nextConfig);
        if (savedDatasets && savedDatasets.length > 0) {
          setDatasets(savedDatasets);
          setDataset(savedDatasets[0]);
          setSelectedDatasetIds([savedDatasets[0].id]);
        }
        const status = await getSystemStatus().catch(() => null);
        if (disposed) return;
        setSystemStatus(status);
        if (status && (!status.sandbox_ready || !status.llm_configured)) setSetupOpen(true);
        checkForUpdate()
          .then((update) => {
            if (!update || disposed) return;
            addToast(
              "info",
              zh ? `发现新版本 v${update.version}` : `Version ${update.version} is available`,
              zh ? "软件更新" : "Update",
              {
                duration: 0,
                action: {
                  label: zh ? "下载并安装" : "Install now",
                  onClick: () => {
                    update.install().catch((err) => addToast("error", errorText(err), zh ? "更新失败" : "Update failed"));
                  },
                },
              },
            );
          })
          .catch(() => undefined);
      } catch {
        if (disposed) return;
        if (Date.now() - startedAt < BACKEND_STARTUP_TIMEOUT_MS) {
          timer = window.setTimeout(loadBackendMetadata, 1500);
        } else {
          setBackendState("failed");
          addToast("error", zh ? "无法连接本地后端服务，请重启应用后重试" : "Cannot reach the local backend; restart the app and try again");
        }
      }
    };
    void loadBackendMetadata();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
    // Runs once at start-up; `zh` only affects messages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const datasetId = dataset?.id;
    if (!datasetId) {
      setHistory([]);
      return;
    }
    listHistory(datasetId).then(setHistory).catch(() => setHistory([]));
  }, [dataset?.id]);

  const refreshHistory = useCallback(async (datasetId: string) => {
    try {
      setHistory(await listHistory(datasetId));
    } catch {
      // 历史记录失败不阻塞绘图
    }
  }, []);

  /** Show a finished plot result and record it in the chat. */
  const applyPlotResult = useCallback(
    (res: PlotResult, datasetId: string, successText: string, failureText?: string) => {
      setResult(res);
      setSelectedPreset((current) => res.preset || current);
      setEditorCode(res.code);
      void refreshHistory(datasetId);
      if (res.run.success) {
        addToast("success", successText);
        pushMessage({ role: "assistant", content: successText });
      } else {
        const lineHint = res.run.error_line ? (zh ? `（第 ${res.run.error_line} 行）` : ` (line ${res.run.error_line})`) : "";
        addToast("error", (failureText || (zh ? "代码执行出错" : "Execution failed")) + lineHint);
        pushMessage({
          role: "assistant",
          content: `${failureText || (zh ? "执行失败" : "Failed")}${lineHint}：${res.run.stderr || res.run.repair_error || (zh ? "未知错误" : "unknown error")}`,
          error: true,
        });
      }
    },
    [addToast, pushMessage, refreshHistory, zh],
  );

  const handleDeleteDataset = async (id: string) => {
    try {
      await deleteDataset(id);
      const next = datasets.filter((d) => d.id !== id);
      setDatasets(next);
      setSelectedDatasetIds((prev) => prev.filter((x) => x !== id));
      if (dataset?.id === id) {
        setDataset(next.length > 0 ? next[0] : null);
        setResult(null);
        setEditorCode("");
        setActiveCard(null);
      }
      addToast("info", zh ? "数据集已成功移除" : "Dataset removed");
    } catch (e) {
      addToast("error", errorText(e), zh ? "删除失败" : "Delete failed");
    }
  };

  const activateDataset = useCallback(
    (item: DatasetInfo, note?: string) => {
      setDataset(item);
      setResult(null);
      setEditorCode("");
      setActiveCard(null);
      setMessages([
        {
          role: "assistant",
          content:
            note ||
            (zh
              ? `已切换至 “${item.name || "未命名"}”：${item.summary.shape.rows} 行 × ${item.summary.shape.cols} 列。`
              : `Switched to "${item.name || "Unnamed"}": ${item.summary.shape.rows} rows × ${item.summary.shape.cols} cols.`),
        },
      ]);
    },
    [zh],
  );

  const handleUpload = useCallback(
    async (files: File[]) => {
      const accepted = files.filter((file) => IMPORT_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext)));
      if (accepted.length < files.length) {
        addToast("warning", zh ? "已跳过不支持的文件类型" : "Skipped unsupported file types");
      }
      if (accepted.length === 0 || busy) return;
      setBusy(true);
      try {
        const loaded = await uploadDatasets(accepted);
        const ds = loaded[0];
        setDatasets((current) => [...current, ...loaded]);
        setSelectedDatasetIds(loaded.map((item) => item.id));
        activateDataset(
          ds,
          zh
            ? `已导入 ${loaded.length} 个数据文件，当前使用 “${ds.name || "未命名"}”：${ds.summary.shape.rows} 行 × ${ds.summary.shape.cols} 列。`
            : `Imported ${loaded.length} files. Active: "${ds.name || "Unnamed"}" (${ds.summary.shape.rows} rows × ${ds.summary.shape.cols} cols).`,
        );
        addToast("success", zh ? `已成功载入 ${loaded.length} 个数据文件` : `Loaded ${loaded.length} files`);
      } catch (e) {
        addToast("error", errorText(e), zh ? "导入失败" : "Import failed");
        pushMessage({ role: "assistant", content: errorText(e), error: true });
      } finally {
        setBusy(false);
      }
    },
    [activateDataset, addToast, busy, pushMessage, zh],
  );

  // Drag & drop import anywhere in the window.
  useEffect(() => {
    let depth = 0;
    const hasFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types || []).includes("Files");
    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth += 1;
      setDragActive(true);
    };
    const onLeave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragActive(false);
    };
    const onOver = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };
    const onDrop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragActive(false);
      void handleUpload(Array.from(event.dataTransfer?.files || []));
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [handleUpload]);

  const combineSelected = async () => {
    if (selectedDatasetIds.length < 2 || busy) return;
    setBusy(true);
    try {
      const combined = await combineDatasets(selectedDatasetIds);
      setDatasets((current) => [...current, combined]);
      setSelectedDatasetIds([combined.id]);
      activateDataset(
        combined,
        zh
          ? `已将 ${selectedDatasetIds.length} 个文件按行拼接，新增来源列 source_file。`
          : `Combined ${selectedDatasetIds.length} files by rows with a source_file column.`,
      );
      addToast("success", zh ? "多表已成功合并" : "Datasets combined");
    } catch (error) {
      addToast("error", errorText(error));
      pushMessage({ role: "assistant", content: errorText(error), error: true });
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
    const controller = new AbortController();
    abortRef.current = controller;
    setStream({ stage: "llm", text: "", startedAt: Date.now() });
    try {
      const kind = result ? "edit" : "generate";
      const body: Record<string, unknown> = result
        ? { dataset_id: dataset.id, code: result.code, instruction: text, preset: selectedPreset, history: nextMessages }
        : { dataset_id: dataset.id, instruction: text, preset: selectedPreset };
      const res = await streamPlot(
        kind,
        body,
        (event) => {
          if (event.type === "token") setStream((s) => (s ? { ...s, text: s.text + event.text } : s));
          else if (event.type === "stage") setStream((s) => (s ? { ...s, stage: event.stage } : s));
        },
        controller.signal,
      );
      if (!res) {
        pushMessage({ role: "assistant", content: zh ? "已取消本次生成。" : "Generation cancelled." });
        return;
      }
      const success = res.repair_attempts
        ? zh
          ? `图已生成，自动修复 ${res.repair_attempts} 次 ✓`
          : `Plot generated with ${res.repair_attempts} auto-repair(s) ✓`
        : zh
        ? "图已生成 ✓"
        : "Plot generated ✓";
      applyPlotResult(res, dataset.id, success, zh ? "生成失败" : "Generation failed");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        pushMessage({ role: "assistant", content: zh ? "已取消本次生成。" : "Generation cancelled." });
      } else {
        addToast("error", errorText(e));
        pushMessage({ role: "assistant", content: errorText(e), error: true });
      }
    } finally {
      abortRef.current = null;
      setStream(null);
      setBusy(false);
    }
  }, [input, dataset, busy, result, selectedPreset, messages, zh, addToast, pushMessage, applyPlotResult]);

  const cancelStream = useCallback(() => abortRef.current?.abort(), []);

  /** Run a plot-producing action with the shared busy state and error handling. */
  const runPlotAction = async (action: () => Promise<PlotResult>, successText: string, failureText?: string) => {
    if (!dataset || busy) return;
    setBusy(true);
    try {
      applyPlotResult(await action(), dataset.id, successText, failureText);
    } catch (e) {
      addToast("error", errorText(e));
      pushMessage({ role: "assistant", content: errorText(e), error: true });
    } finally {
      setBusy(false);
    }
  };

  const runEditor = async () => {
    if (!dataset) return;
    await runPlotAction(
      () => runCode(dataset.id, editorCode, selectedPreset),
      zh ? "代码已重新执行渲染 ✓" : "Code re-rendered ✓",
      zh ? "运行失败" : "Run error",
    );
  };

  const applyParameterChange = async (parameter: CodeParameter, value: string) => {
    if (!dataset || !result) return;
    await runPlotAction(
      async () => {
        const res = await applyParameter(dataset.id, result.code, parameter, value, selectedPreset);
        setActiveCard(res.statements.find((s) => s.start <= parameter.start_line && s.end >= parameter.start_line) ?? null);
        return res;
      },
      zh ? `已应用“${parameter.label}”并重新渲染 ✓` : `Applied "${parameter.name}" ✓`,
    );
  };

  const restore = async (revision: RevisionSummary) => {
    if (!dataset || !revision.success) return;
    setActiveCard(null);
    await runPlotAction(() => restoreRevision(revision.id), zh ? "已恢复历史版本并生成新版本 ✓" : "Version restored as a new revision ✓");
  };

  const handleInteractiveAdjust = async (action: string, params: Record<string, unknown>) => {
    if (!dataset || !result) return;
    await runPlotAction(
      () => interactiveAdjustPlot({ dataset_id: dataset.id, code: result.code, action, params, preset: selectedPreset }),
      zh ? `🎯 已完成画布调整（${action}），代码已同步更新` : `🎯 Adjustment applied (${action}), code updated`,
    );
  };

  const handleRunCritic = async (useAi: boolean) => {
    if (!result?.revision_id || busy) return;
    setBusy(true);
    try {
      const report = await critiquePlot(result.revision_id, useAi);
      const lines = [
        zh ? `【🔍 排版体检】综合评分：${report.score}/100` : `【🔍 Layout critique】Score: ${report.score}/100`,
        ...report.suggestions.map((s) => `• ${s}`),
      ];
      if (report.ai) {
        if (report.ai.available) {
          lines.push(zh ? `\n【👁️ AI 视觉审查】评分：${report.ai.score}/100` : `\n【👁️ AI review】Score: ${report.ai.score}/100`);
          lines.push(...(report.ai.issues || []).map((s) => `⚠ ${s}`));
          lines.push(...(report.ai.suggestions || []).map((s) => `→ ${s}`));
        } else {
          lines.push(`\n${report.ai.error}`);
        }
      }
      pushMessage({ role: "assistant", content: lines.join("\n") });
      addToast("info", zh ? `体检得分：${report.score}/100` : `Critique score: ${report.score}/100`);
      const aiSuggestions = report.ai?.available ? report.ai.suggestions || [] : [];
      if (report.repair_prompt || aiSuggestions.length) {
        setInput(
          [report.repair_prompt, ...aiSuggestions.map((s) => `- ${s}`)].filter(Boolean).join("\n") ||
            (zh ? "请优化该图的视觉排版" : "Please improve the layout"),
        );
      }
    } catch (e) {
      addToast("error", errorText(e));
      pushMessage({ role: "assistant", content: errorText(e), error: true });
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateRevision = async (id: string, patch: { label?: string; starred?: boolean }) => {
    try {
      const updated = await updateRevision(id, patch);
      setHistory((items) => items.map((item) => (item.id === id ? { ...item, label: updated.label, starred: updated.starred } : item)));
    } catch (e) {
      addToast("error", errorText(e));
    }
  };

  const enableMockMode = async () => {
    const next = await updateLLMConfig({
      base_url: llmConfig.base_url,
      model: llmConfig.model,
      mock: true,
      auto_repair_attempts: llmConfig.auto_repair_attempts,
      send_data_values: llmConfig.send_data_values,
    });
    setLlmConfig(next);
    await refreshSystemStatus();
  };

  const onPlotModalSuccess = (res: PlotResult, text: string) => {
    if (!dataset) return;
    applyPlotResult(res, dataset.id, text);
  };

  return (
    <div className="app">
      <Header
        language={language}
        llmConfig={llmConfig}
        backendState={backendState}
        sandboxReady={systemStatus ? systemStatus.sandbox_ready : null}
        busy={busy}
        hasDataset={!!dataset}
        canBatch={Boolean(result?.code && datasets.length > 1)}
        onToggleLanguage={toggleLanguage}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenSetup={() => {
          void refreshSystemStatus();
          setSetupOpen(true);
        }}
        onUploadFiles={(files) => void handleUpload(files)}
        onOpenMimic={() => setMimicOpen(true)}
        onOpenComposer={() => setComposerOpen(true)}
        onOpenTemplates={() => setTemplatesOpen(true)}
        onOpenBatch={() => setBatchOpen(true)}
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
          onSelectDataset={(item) => activateDataset(item)}
          onToggleDatasetSelect={(id, checked) => {
            setSelectedDatasetIds((current) => (checked ? [...current, id] : current.filter((x) => x !== id)));
          }}
          onCombineSelected={() => void combineSelected()}
          onSelectPreset={setSelectedPreset}
          onRestoreRevision={(rev) => void restore(rev)}
          onDeleteDataset={(id) => void handleDeleteDataset(id)}
          onOpenWorkbench={setWorkbenchDataset}
          onUpdateRevision={(id, patch) => void handleUpdateRevision(id, patch)}
          onCompareRevisions={(older, newer) => setDiffPair({ older, newer })}
        />

        <PreviewCanvas
          language={language}
          result={result}
          busy={busy}
          onRunCritic={(useAi) => void handleRunCritic(useAi)}
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
          stream={stream}
          onCancel={cancelStream}
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
          onSelectCard={setActiveCard}
          onApplyParameter={applyParameterChange}
          onRunEditor={runEditor}
          onCopyCode={(_code, ok) =>
            ok
              ? addToast("info", zh ? "代码已复制到剪贴板 ✓" : "Code copied to clipboard ✓")
              : addToast("error", zh ? "复制失败，请在源码框中手动选择复制" : "Copy failed; select the code manually")
          }
        />
      )}

      {setupOpen && systemStatus && (
        <SetupWizard
          language={language}
          status={systemStatus}
          onStatusChange={setSystemStatus}
          onOpenSettings={() => setSettingsOpen(true)}
          onEnableMock={enableMockMode}
          onClose={() => setSetupOpen(false)}
        />
      )}

      {settingsOpen && (
        <SettingsDialog
          config={llmConfig}
          onClose={() => {
            setSettingsOpen(false);
            void refreshSystemStatus();
          }}
          onSaved={(newCfg) => {
            setLlmConfig(newCfg);
            addToast("success", zh ? "设置已成功保存" : "Settings saved");
          }}
          onOpenSetup={() => {
            setSettingsOpen(false);
            void refreshSystemStatus();
            setSetupOpen(true);
          }}
          language={language}
        />
      )}

      {statsOpen && dataset && result && (
        <StatsModal
          language={language}
          dataset={dataset}
          code={result.code}
          preset={selectedPreset}
          onClose={() => setStatsOpen(false)}
          onSuccess={(res, kind) =>
            onPlotModalSuccess(
              res,
              kind === "regression"
                ? zh
                  ? `📈 回归拟合完成：${res.regression?.equation || ""}，R² = ${res.regression?.r_squared.toFixed(4) ?? "-"}`
                  : `📈 Fit added: ${res.regression?.equation || ""}, R² = ${res.regression?.r_squared.toFixed(4) ?? "-"}`
                : zh
                ? "⚡ 统计检验完成，已添加显著性标注"
                : "⚡ Significance brackets added",
            )
          }
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
          onSuccess={(res) => onPlotModalSuccess(res, zh ? "📊 组合大图编排完成" : "📊 Multi-panel figure composed")}
        />
      )}

      {mimicOpen && dataset && (
        <MimicModal
          language={language}
          dataset={dataset}
          preset={selectedPreset}
          onClose={() => setMimicOpen(false)}
          onSuccess={(res) => onPlotModalSuccess(res, zh ? "🎨 论文图版式复刻完成" : "🎨 Paper figure style replicated")}
        />
      )}

      {templatesOpen && dataset && (
        <TemplateGallery
          language={language}
          dataset={dataset}
          preset={selectedPreset}
          onClose={() => setTemplatesOpen(false)}
          onSuccess={(res, name) => onPlotModalSuccess(res, zh ? `🧪 已用模板生成：${name}` : `🧪 Created from template: ${name}`)}
        />
      )}

      {complianceOpen && result?.revision_id && (
        <ComplianceModal
          language={language}
          revisionId={result.revision_id}
          datasetId={dataset?.id}
          code={result.code}
          preset={selectedPreset}
          isPlotly={Boolean(result.run.interactive)}
          onClose={() => setComplianceOpen(false)}
          onApplyPrompt={(prompt) => {
            setInput(prompt);
            addToast("info", zh ? "修复建议已填入对话框" : "Prompt applied to chat");
          }}
          onFitted={(res, label) => onPlotModalSuccess(res, zh ? `📐 已适配版面：${label}` : `📐 Resized to ${label}`)}
        />
      )}

      {batchOpen && result && (
        <BatchModal
          language={language}
          datasets={datasets}
          currentDatasetId={dataset?.id}
          code={result.code}
          preset={selectedPreset}
          onClose={() => setBatchOpen(false)}
          onDone={() => dataset && void refreshHistory(dataset.id)}
        />
      )}

      {workbenchDataset && (
        <DataWorkbench
          language={language}
          dataset={workbenchDataset}
          datasets={datasets}
          onClose={() => setWorkbenchDataset(null)}
          onCreated={(created) => {
            setDatasets((current) => [...current, created]);
            setSelectedDatasetIds([created.id]);
            activateDataset(
              created,
              zh
                ? `已生成新数据集 “${created.name}”：${created.summary.shape.rows} 行 × ${created.summary.shape.cols} 列。`
                : `Created "${created.name}": ${created.summary.shape.rows} rows × ${created.summary.shape.cols} cols.`,
            );
            addToast("success", zh ? "新数据集已生成" : "Dataset created");
          }}
        />
      )}

      {diffPair && (
        <RevisionDiffModal language={language} olderId={diffPair.older} newerId={diffPair.newer} onClose={() => setDiffPair(null)} />
      )}

      {dragActive && (
        <div className="drop-overlay">
          <div className="drop-overlay-box">
            <span>📥</span>
            <strong>{zh ? "松开鼠标导入数据文件" : "Drop to import data files"}</strong>
            <small>CSV · TSV · TXT · Excel · JSON</small>
          </div>
        </div>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
