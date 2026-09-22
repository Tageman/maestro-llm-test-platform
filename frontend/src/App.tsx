import { useEffect, useMemo, useState } from "react";

import {
  approveFlows,
  createGeneration,
  getGeneratedFlow,
  getHealth,
  getWorkbookValidation,
  uploadWorkbook,
} from "./api";
import { RunConsole } from "./features/runs/RunConsole";
import type {
  GeneratedFlowDetail,
  GenerationFlowSummary,
  GenerationSummary,
  HealthResponse,
  ValidationIssue,
  ValidationReport,
  WorkbookSummary,
} from "./types";

type BusyState = "upload" | "generate" | "detail" | "approve" | null;
type RunMode = "review" | "unattended";

const flowStatusLabel: Record<GenerationFlowSummary["status"], string> = {
  generated: "待确认",
  needs_review: "需复核",
  approved: "已确认",
  failed: "阻断",
};

function CountCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="count-cell">
      <span>{label}</span>
      <strong>{String(value).padStart(2, "0")}</strong>
    </div>
  );
}

function IssueTable({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="empty-state empty-state--success">
        <span>✓</span>
        <div>
          <strong>结构与业务校验通过</strong>
          <p>字段、配置、引用和 Fixture DAG 未发现问题。</p>
        </div>
      </div>
    );
  }
  return (
    <div className="issue-table" role="table" aria-label="工作簿校验问题">
      {issues.map((issue, index) => (
        <article className={`issue issue--${issue.severity}`} key={`${issue.code}-${index}`}>
          <span className="issue__level">{issue.severity === "error" ? "ERROR" : "WARN"}</span>
          <div>
            <div className="issue__title">
              <strong>{issue.code}</strong>
              <code>
                {issue.sheet ?? "workbook"}
                {issue.row ? `!${issue.column ?? ""}${issue.row}` : ""}
              </code>
            </div>
            <p>{issue.message}</p>
            {issue.suggestion && <small>{issue.suggestion}</small>}
          </div>
        </article>
      ))}
    </div>
  );
}

function FlowBadge({ flow }: { flow: GenerationFlowSummary }) {
  return (
    <span className={`flow-badge flow-badge--${flow.status}`}>
      {flowStatusLabel[flow.status]}
    </span>
  );
}

function App() {
  const initialRunId = useMemo(
    () => new URLSearchParams(window.location.search).get("run") ?? undefined,
    [],
  );
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [workbook, setWorkbook] = useState<WorkbookSummary | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [generation, setGeneration] = useState<GenerationSummary | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null);
  const [flowDetail, setFlowDetail] = useState<GeneratedFlowDetail | null>(null);
  const [mode, setMode] = useState<RunMode>("review");
  const [busy, setBusy] = useState<BusyState>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal).then(setHealth).catch(() => setHealth(null));
    return () => controller.abort();
  }, []);

  const loadFlow = async (flowId: string, activeGeneration = generation) => {
    if (!activeGeneration) return;
    setSelectedFlowId(flowId);
    setBusy("detail");
    setError(null);
    try {
      setFlowDetail(await getGeneratedFlow(activeGeneration.generation_id, flowId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取 Flow 详情");
    } finally {
      setBusy(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setBusy("upload");
    setError(null);
    setGeneration(null);
    setFlowDetail(null);
    try {
      const imported = await uploadWorkbook(file);
      const report = await getWorkbookValidation(imported.workbook_id);
      setWorkbook(imported);
      setValidation(report);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入工作簿失败");
    } finally {
      setBusy(null);
    }
  };

  const handleGenerate = async () => {
    if (!workbook || !validation?.valid) return;
    setBusy("generate");
    setError(null);
    try {
      const created = await createGeneration(workbook.workbook_id, mode);
      setGeneration(created);
      if (created.flows[0]) await loadFlow(created.flows[0].flow_id, created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成预览失败");
    } finally {
      setBusy(null);
    }
  };

  const handleApprove = async (flowIds: string[]) => {
    if (!generation || flowIds.length === 0) return;
    setBusy("approve");
    setError(null);
    try {
      const updated = await approveFlows(generation.generation_id, flowIds);
      setGeneration(updated);
      if (selectedFlowId) await loadFlow(selectedFlowId, updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "确认 Flow 失败");
    } finally {
      setBusy(null);
    }
  };

  const safeBatch = useMemo(
    () =>
      generation?.flows
        .filter((flow) => !flow.approved && flow.syntax_valid && flow.warning_count === 0)
        .map((flow) => flow.flow_id) ?? [],
    [generation],
  );

  const approvedRatio = generation
    ? `${generation.approved_flow_count}/${generation.flow_count}`
    : "0/0";

  const selectMode = (nextMode: RunMode) => {
    if (busy !== null || nextMode === mode) return;
    setMode(nextMode);
    setGeneration(null);
    setSelectedFlowId(null);
    setFlowDetail(null);
  };

  return (
    <main className="workbench">
      <div className="grid-noise" aria-hidden="true" />

      <header className="masthead">
        <a className="brand" href="#top">
          <span className="brand__mark">M</span>
          <span>
            <strong>TEST FOUNDRY</strong>
            <small>OFFLINE GENERATION BENCH</small>
          </span>
        </a>
        <div className="milestone">
          <span>M3</span>
          <div>
            <strong>无人值守闭环</strong>
            <small>PYTEST → MCP REPAIR → RESULT</small>
          </div>
        </div>
        <div className={`api-light ${health ? "api-light--on" : ""}`}>
          <i /> {health ? `API ${health.version}` : "API OFFLINE"}
        </div>
      </header>

      <section className="intro" id="top">
        <div>
          <p className="kicker">01 / SOURCE INTAKE</p>
          <h1>把自然语言，<br />压进<span>可审查</span>的执行结构。</h1>
        </div>
        <div className="intro__note">
          <p>源 Excel 只读。模型只产出 Flow IR，YAML 由确定性编译器生成。</p>
          <code>SCHEMA 1.0 · NO COORDINATES · REVIEW GATE</code>
        </div>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <strong>WORKBENCH BLOCKED</strong>
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>关闭</button>
        </div>
      )}

      {!initialRunId && <section className="intake-panel" aria-label="Excel 导入">
        <label className="file-drop">
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <span className="file-drop__index">A</span>
          <div>
            <strong>{file?.name ?? "选择三 Sheet 测试用例工作簿"}</strong>
            <small>{file ? `${(file.size / 1024).toFixed(1)} KiB` : "仅支持 .xlsx，最大 20 MiB"}</small>
          </div>
          <em>{file ? "CHANGE" : "BROWSE"}</em>
        </label>
        <button
          className="action-button"
          type="button"
          disabled={!file || busy !== null}
          onClick={() => void handleUpload()}
        >
          {busy === "upload" ? "正在建立快照" : "导入并校验"}
          <span>→</span>
        </button>
      </section>}

      {workbook && validation && (
        <section className="validation-section">
          <div className="section-title">
            <div>
              <p className="kicker">02 / STRUCTURE CHECK</p>
              <h2>工作簿校验</h2>
            </div>
            <div className={`verdict verdict--${validation.valid ? "pass" : "fail"}`}>
              {validation.valid ? "PASS" : "BLOCKED"}
            </div>
          </div>

          <div className="workbook-meta">
            <div>
              <span>SOURCE</span>
              <strong>{workbook.source_filename}</strong>
              <code>{workbook.source_sha256.slice(0, 18)}…</code>
            </div>
            <div className="count-strip">
              <CountCell label="CASE" value={workbook.counts.enabled_cases} />
              <CountCell label="FIXTURE" value={workbook.counts.enabled_fixtures} />
              <CountCell label="CONFIG" value={workbook.counts.configs} />
              <CountCell label="ERROR" value={workbook.counts.errors} />
            </div>
          </div>

          <IssueTable issues={validation.issues} />

          {Object.entries(workbook.fixture_plans).map(([caseId, fixtures]) => (
            <div className="fixture-chain" key={caseId}>
              <span>FIXTURE PLAN</span>
              <strong>{caseId}</strong>
              <div>
                {fixtures.map((fixture, index) => (
                  <span key={fixture}>
                    {index > 0 && <i>→</i>}{fixture}
                  </span>
                ))}
              </div>
            </div>
          ))}

          <div className="mode-picker" role="group" aria-label="生成模式">
            <button
              type="button"
              aria-pressed={mode === "review"}
              className={mode === "review" ? "mode-picker__active" : ""}
              disabled={busy !== null}
              onClick={() => selectMode("review")}
            >
              <span>R</span>
              <div><strong>人工预览</strong><small>生成后逐项或批量确认</small></div>
            </button>
            <button
              type="button"
              aria-pressed={mode === "unattended"}
              className={mode === "unattended" ? "mode-picker__active" : ""}
              disabled={busy !== null}
              onClick={() => selectMode("unattended")}
            >
              <span>U</span>
              <div><strong>无人值守</strong><small>M1 生成后自动进入执行就绪</small></div>
            </button>
          </div>

          <button
            className="generate-button"
            type="button"
            disabled={!validation.valid || busy !== null}
            onClick={() => void handleGenerate()}
          >
            <span>{busy === "generate" ? "正在生成并检查语法" : "生成全部 IR 与 YAML"}</span>
            <small>{validation.valid ? `${mode.toUpperCase()} MODE` : "FIX ERRORS FIRST"}</small>
          </button>
        </section>
      )}

      {generation && (
        <section className="review-section">
          <div className="section-title">
            <div>
              <p className="kicker">
                {generation.mode === "review" ? "03 / HUMAN REVIEW GATE" : "03 / UNATTENDED OUTPUT"}
              </p>
              <h2>{generation.mode === "review" ? "生成审查台" : "无人值守生成结果"}</h2>
            </div>
            <div className="approval-meter">
              <span>APPROVED</span>
              <strong>{approvedRatio}</strong>
            </div>
          </div>

          <div className="review-grid">
            <aside className="flow-rail">
              <div className="flow-rail__head">
                <span>FLOW QUEUE</span>
                <button
                  type="button"
                  disabled={safeBatch.length === 0 || busy !== null}
                  onClick={() => void handleApprove(safeBatch)}
                >
                  批量确认无警告项
                </button>
              </div>
              {generation.flows.map((flow, index) => (
                <button
                  type="button"
                  className={`flow-item ${selectedFlowId === flow.flow_id ? "flow-item--active" : ""}`}
                  key={flow.flow_id}
                  onClick={() => void loadFlow(flow.flow_id)}
                >
                  <span className="flow-item__number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="flow-item__copy">
                    <small>{flow.flow_kind.toUpperCase()}</small>
                    <strong>{flow.flow_id}</strong>
                    <em>{flow.syntax_valid ? "SYNTAX OK" : "SYNTAX ERROR"}</em>
                  </span>
                  <FlowBadge flow={flow} />
                </button>
              ))}
            </aside>

            <div className="flow-inspector">
              {flowDetail ? (
                <>
                  <header className="inspector-head">
                    <div>
                      <small>{flowDetail.flow_kind.toUpperCase()} / {flowDetail.flow_id}</small>
                      <h3>{flowDetail.name}</h3>
                    </div>
                    <button
                      type="button"
                      disabled={flowDetail.approved || !flowDetail.syntax_valid || busy !== null}
                      onClick={() => void handleApprove([flowDetail.flow_id])}
                    >
                      {flowDetail.approved ? "已确认" : "确认此 Flow"}
                    </button>
                  </header>

                  {flowDetail.warnings.length > 0 && (
                    <div className="warning-list">
                      {flowDetail.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                    </div>
                  )}

                  <div className="mapping-table">
                    <div className="mapping-table__head">
                      <span>源步骤</span><span>Flow IR</span><span>选择器 / 断言</span>
                    </div>
                    {flowDetail.mappings.map((mapping) => (
                      <article key={`${mapping.source_field}-${mapping.source_ordinal}`}>
                        <div>
                          <small>{mapping.source_field === "steps" ? "ACTION" : "EXPECTED"} {mapping.source_ordinal}</small>
                          <p>{mapping.source_text}</p>
                        </div>
                        <code>{mapping.command_type}</code>
                        <div className="selector-cell">
                          {mapping.selector_value ? (
                            <><small>{mapping.selector_strategy}</small><strong>{mapping.selector_value}</strong></>
                          ) : <span>NO SELECTOR</span>}
                          {mapping.assertion && <em>ASSERTION</em>}
                        </div>
                      </article>
                    ))}
                  </div>

                  <div className="yaml-panel">
                    <div>
                      <span>COMPILED MAESTRO YAML</span>
                      <code>{flowDetail.syntax_valid ? "CHECK-SYNTAX / OK" : "CHECK-SYNTAX / FAILED"}</code>
                    </div>
                    <pre>{flowDetail.yaml}</pre>
                  </div>
                </>
              ) : (
                <div className="empty-inspector">
                  {busy === "detail" ? "LOADING FLOW…" : "SELECT A FLOW TO INSPECT"}
                </div>
              )}
            </div>
          </div>

          {generation.status === "ready" && (
            <div className="ready-strip">
              <strong>{generation.mode === "review" ? "REVIEW COMPLETE" : "AUTO APPROVED"}</strong>
              <span>
                {generation.mode === "review"
                  ? "全部 Flow 已确认，可以连接模拟器创建执行 Run。"
                  : "全部 Flow 已自动确认，可以直接创建执行 Run。"}
              </span>
            </div>
          )}
        </section>
      )}

      {initialRunId ? (
        <RunConsole initialRunId={initialRunId} onError={setError} />
      ) : generation?.status === "ready" && (
        <RunConsole generation={generation} onError={setError} />
      )}

      <footer>
        <span>仅限受控本地环境 · Excel / YAML / 日志可能包含测试账号与数据</span>
        <span>FLOW IR 1.0 · COMPILER 1.0</span>
      </footer>
    </main>
  );
}

export default App;
