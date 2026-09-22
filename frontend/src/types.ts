export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
  api_version: "v1";
  time: string;
};

export type WorkbookCounts = {
  cases: number;
  fixtures: number;
  configs: number;
  enabled_cases: number;
  enabled_fixtures: number;
  errors: number;
  warnings: number;
};

export type WorkbookSummary = {
  workbook_id: string;
  source_filename: string;
  source_sha256: string;
  imported_at: string;
  status: "imported" | "valid" | "invalid";
  counts: WorkbookCounts;
  fixture_plans: Record<string, string[]>;
};

export type ValidationIssue = {
  code: string;
  severity: "error" | "warning";
  message: string;
  sheet: string | null;
  row: number | null;
  column: string | null;
  entity_id: string | null;
  field: string | null;
  suggestion: string | null;
};

export type ValidationReport = {
  workbook_id: string;
  valid: boolean;
  issues: ValidationIssue[];
};

export type FlowGenerationStatus =
  | "generated"
  | "needs_review"
  | "approved"
  | "failed";

export type GenerationFlowSummary = {
  flow_id: string;
  flow_kind: "case" | "fixture";
  name: string;
  status: FlowGenerationStatus;
  warning_count: number;
  syntax_valid: boolean;
  approved: boolean;
};

export type GenerationSummary = {
  generation_id: string;
  workbook_id: string;
  mode: "review" | "unattended";
  status: "pending" | "generating" | "awaiting_review" | "ready" | "failed";
  flow_count: number;
  approved_flow_count: number;
  flows: GenerationFlowSummary[];
  fixture_plans: Record<string, string[]>;
  created_at: string;
  updated_at: string;
  terminal_reason: string | null;
};

export type StepMapping = {
  source_field: "steps" | "expected_results";
  source_ordinal: number;
  source_text: string;
  command_type: string;
  selector_strategy: string | null;
  selector_value: string | null;
  assertion: boolean;
  warning: string | null;
};

export type GeneratedFlowDetail = {
  flow_id: string;
  flow_kind: "case" | "fixture";
  name: string;
  status: FlowGenerationStatus;
  ir: Record<string, unknown>;
  yaml: string;
  mappings: StepMapping[];
  warnings: string[];
  syntax_valid: boolean;
  syntax_output: string | null;
  syntax_attempts: number;
  syntax_repairs: number;
  approved: boolean;
};

export type RunState =
  | "CREATED"
  | "VALIDATING"
  | "VALIDATION_FAILED"
  | "GENERATING"
  | "GENERATION_FAILED"
  | "AWAITING_REVIEW"
  | "READY"
  | "PREPARING_DEVICE"
  | "RUNNING"
  | "DIAGNOSING"
  | "REPAIRING"
  | "FINALIZING"
  | "COMPLETED"
  | "COMPLETED_WITH_FAILURES"
  | "FAILED"
  | "CANCELLED";

export type RunSummary = {
  run_id: string;
  generation_id: string;
  workbook_id: string;
  state: RunState;
  mode: "review" | "unattended";
  created_at: string;
  updated_at: string;
  started_at: string | null;
  ended_at: string | null;
  device_id: string | null;
  avd_name: string | null;
  app_id: string | null;
  selected_case_ids: string[];
  pytest_node_ids: string[];
  case_counts: Record<string, number>;
  events_cursor: number;
  cancel_requested: boolean;
  terminal_reason: string | null;
  repair_count: number;
  result_workbook_available: boolean;
  html_report_artifact_id: string | null;
};

export type FailureType =
  | "YAML_SYNTAX" | "LOCATOR" | "ASSERTION" | "ENVIRONMENT"
  | "FIXTURE" | "TIMEOUT" | "UNKNOWN";

export type Attempt = {
  attempt_id: string;
  ordinal: number;
  state: string;
  failure_type: FailureType | null;
  failure_reason: string | null;
  failed_step: number | null;
  failed_selector: string | null;
  exit_code: number | null;
  artifact_ids: string[];
  repair_id: string | null;
};

export type RepairRecord = {
  repair_id: string;
  case_id: string;
  attempt_id: string;
  failure_type: FailureType;
  evidence_artifact_ids: string[];
  reason: string;
  before_selector: string;
  after_selector: string;
  yaml_diff_path: string;
  approved_automatically: boolean;
  created_at: string;
};

export type Artifact = {
  artifact_id: string;
  kind: string;
  relative_path: string;
  media_type: string;
  sha256: string;
  case_id: string | null;
  attempt_id: string | null;
  created_at: string;
};

export type CaseRunDetail = {
  case_id: string;
  state: string;
  fixture_plan: string[];
  attempts: Attempt[];
  repairs: RepairRecord[];
  artifacts: Artifact[];
  business_result: string | null;
  cleanup_result: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
};

export type Problem = {
  code: string;
  message: string;
  request_id?: string;
  details?: Array<Record<string, unknown>>;
  retryable?: boolean;
};
