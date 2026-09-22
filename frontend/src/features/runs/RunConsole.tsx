import { useEffect, useMemo, useState } from "react";

import {
  artifactUrl,
  cancelRun,
  createRun,
  getCaseRun,
  getRun,
  resultWorkbookUrl,
} from "../../api";
import type { CaseRunDetail, GenerationSummary, RunState, RunSummary } from "../../types";

const terminalStates = new Set<RunState>([
  "VALIDATION_FAILED", "GENERATION_FAILED", "COMPLETED",
  "COMPLETED_WITH_FAILURES", "FAILED", "CANCELLED",
]);

const phaseLabel: Record<RunState, string> = {
  CREATED: "已创建", VALIDATING: "校验输入", VALIDATION_FAILED: "校验失败",
  GENERATING: "生成 pytest", GENERATION_FAILED: "生成失败",
  AWAITING_REVIEW: "等待确认", READY: "等待设备",
  PREPARING_DEVICE: "准备模拟器", RUNNING: "pytest / Maestro 执行",
  DIAGNOSING: "诊断", REPAIRING: "修复", FINALIZING: "聚合证据",
  COMPLETED: "全部通过", COMPLETED_WITH_FAILURES: "执行完成，有失败",
  FAILED: "运行失败", CANCELLED: "已取消",
};

type Props = {
  generation?: GenerationSummary;
  initialRunId?: string;
  onError: (message: string) => void;
};

export function RunConsole({ generation, initialRunId, onError }: Props) {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [busy, setBusy] = useState(Boolean(initialRunId));
  const [caseDetails, setCaseDetails] = useState<CaseRunDetail[]>([]);

  useEffect(() => {
    if (!initialRunId) return;
    setBusy(true);
    void getRun(initialRunId)
      .then(setRun)
      .catch((caught: unknown) =>
        onError(caught instanceof Error ? caught.message : "读取 Run 失败"),
      )
      .finally(() => setBusy(false));
  }, [initialRunId, onError]);

  useEffect(() => {
    if (!run || terminalStates.has(run.state)) return undefined;
    const timer = window.setInterval(() => {
      void getRun(run.run_id).then(setRun).catch((caught: unknown) =>
        onError(caught instanceof Error ? caught.message : "读取 Run 失败"),
      );
    }, 800);
    return () => window.clearInterval(timer);
  }, [run, onError]);

  useEffect(() => {
    if (!run || !terminalStates.has(run.state)) return;
    const caseIds = run.selected_case_ids;
    void Promise.all(caseIds.map((caseId) => getCaseRun(run.run_id, caseId)))
      .then(setCaseDetails)
      .catch((caught: unknown) =>
        onError(caught instanceof Error ? caught.message : "读取 Case 证据失败"),
      );
  }, [run?.run_id, run?.state, run?.selected_case_ids, onError]);

  const outcome = useMemo(
    () => Object.entries(run?.case_counts ?? {})
      .map(([state, count]) => `${state} ${count}`).join(" · "),
    [run],
  );

  const start = async () => {
    if (!generation) return;
    setBusy(true);
    try {
      const created = await createRun(generation.generation_id);
      setRun(created);
      const url = new URL(window.location.href);
      url.searchParams.set("run", created.run_id);
      window.history.replaceState({}, "", url);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "创建 Run 失败");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!run) return;
    setBusy(true);
    try {
      setRun(await cancelRun(run.run_id));
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "取消 Run 失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="run-console" aria-label="M3 无人值守执行与修复控制台">
      <div className="run-console__head">
        <div><p className="kicker">04 / EMULATOR EXECUTION</p><h2>真实执行控制台</h2></div>
        <span className={`run-state run-state--${(run?.state ?? "READY").toLowerCase()}`}>
          {run ? run.state : "NOT STARTED"}
        </span>
      </div>
      {!run ? (
        <div className="run-launch">
          <div>
            <strong>pytest Fixture → Maestro CLI</strong>
            <p>将连接唯一 Android 模拟器，校验 AVD 与目标包后执行。Maestro Studio 必须保持断开。</p>
          </div>
          {initialRunId ? (
            <strong>{busy ? "正在读取 Run 证据…" : "Run 不存在或无法读取"}</strong>
          ) : (
            <button type="button" disabled={busy || !generation} onClick={() => void start()}>
              {busy ? "正在创建" : "连接模拟器并执行"}<span>→</span>
            </button>
          )}
        </div>
      ) : (
        <div className="run-grid">
          <div className="run-phase">
            <small>CURRENT PHASE</small><strong>{phaseLabel[run.state]}</strong><code>{run.run_id}</code>
          </div>
          <dl>
            <div><dt>DEVICE</dt><dd>{run.device_id ?? "等待选择"}</dd></div>
            <div><dt>AVD</dt><dd>{run.avd_name ?? "等待校验"}</dd></div>
            <div><dt>APP</dt><dd>{run.app_id ?? "等待校验"}</dd></div>
            <div><dt>EVENTS</dt><dd>{run.events_cursor}</dd></div>
            <div><dt>PYTEST ITEMS</dt><dd>{run.pytest_node_ids.length}</dd></div>
            <div><dt>RESULT</dt><dd>{outcome || "执行中"}</dd></div>
            <div><dt>REPAIRS</dt><dd>{run.repair_count}</dd></div>
          </dl>
          {run.terminal_reason && <p className="run-reason">{run.terminal_reason}</p>}
          {!terminalStates.has(run.state) && (
            <button className="run-cancel" type="button" disabled={busy} onClick={() => void cancel()}>
              安全终止
            </button>
          )}
        </div>
      )}
      {run && terminalStates.has(run.state) && (
        <section className="evidence-console" aria-label="运行证据与修复详情">
          <header>
            <div>
              <small>05 / EVIDENCE LEDGER</small>
              <h3>尝试、修复与产物</h3>
            </div>
            <div className="result-links">
              {run.html_report_artifact_id && (
                <a className="result-download" href={artifactUrl(run.run_id, run.html_report_artifact_id)}>
                  下载 HTML 报告 <span>↓</span>
                </a>
              )}
              {run.result_workbook_available && (
                <a className="result-download" href={resultWorkbookUrl(run.run_id)}>
                  下载结果 Excel <span>↓</span>
                </a>
              )}
            </div>
          </header>
          {caseDetails.map((detail) => (
            <article className="case-evidence" key={detail.case_id}>
              <div className="case-evidence__summary">
                <div><small>CASE</small><strong>{detail.case_id}</strong></div>
                <span className={`case-outcome case-outcome--${detail.state.toLowerCase()}`}>
                  {detail.state}
                </span>
                <code>{detail.attempts.length} ATTEMPT · {detail.repairs.length} REPAIR</code>
              </div>
              <div className="attempt-lane">
                {detail.attempts.map((attempt) => (
                  <div className="attempt-card" key={attempt.attempt_id}>
                    <span>A{attempt.ordinal}</span>
                    <div>
                      <strong>{attempt.state}</strong>
                      <small>{attempt.failure_type ?? "NO FAILURE"}</small>
                    </div>
                    {attempt.failure_reason && <p>{attempt.failure_reason}</p>}
                    <code>EXIT {attempt.exit_code ?? "—"} · {attempt.artifact_ids.length} FILES</code>
                  </div>
                ))}
              </div>
              {detail.repairs.map((repair) => (
                <div className="repair-strip" key={repair.repair_id}>
                  <span>CONTROLLED PATCH</span>
                  <div>
                    <code>{repair.before_selector}</code><i>→</i><code>{repair.after_selector}</code>
                    <p>{repair.reason}</p>
                  </div>
                  {detail.artifacts.find((item) => item.relative_path === repair.yaml_diff_path) && (
                    <a href={artifactUrl(
                      run.run_id,
                      detail.artifacts.find((item) => item.relative_path === repair.yaml_diff_path)!.artifact_id,
                    )}>查看 DIFF</a>
                  )}
                </div>
              ))}
              <details className="artifact-panel">
                <summary>完整证据账本 · {detail.artifacts.length} FILES</summary>
                <div className="artifact-ledger">
                  {detail.artifacts.map((artifact) => (
                    <a href={artifactUrl(run.run_id, artifact.artifact_id)} key={artifact.artifact_id}>
                      <span>{artifact.attempt_id ?? "REPAIR"} · {artifact.kind.replaceAll("_", " ")}</span>
                      <code>{artifact.sha256.slice(0, 10)}</code>
                    </a>
                  ))}
                </div>
              </details>
            </article>
          ))}
        </section>
      )}
    </section>
  );
}
