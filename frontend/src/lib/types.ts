export type TaskStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'WAITING_APPROVAL'
  | 'PAUSED_QUOTA'
  | 'FAILED'
  | 'CANCELLED'
  | 'COMPLETED';

export interface TaskSummary {
  id: string;
  status: TaskStatus;
  objective: string;
  created_at: string;
  updated_at: string;
  last_error?: string | null;
}

export interface ApprovalRequest {
  id: string;
  task_id: string;
  action_id: string;
  action: string;
  reason: string;
  impact: string;
  rollback: string;
  requested_at: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
}

export interface ProviderQuota {
  provider: string;
  remaining_requests: number;
  reset_at?: string | null;
  enabled: boolean;
}

export interface ModelQuotaResponse {
  primary: string;
  selected_provider?: string | null;
  providers: ProviderQuota[];
}

export interface EventMessage {
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface SelfImproveReport {
  id: string;
  started_at: string;
  ended_at?: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  tests_passed: boolean;
  risk_summary: string;
  actions: string[];
  findings: Array<{
    id: string;
    gap: string;
    proposal: string;
    expected_impact: string;
    created_at: string;
  }>;
}

export interface CodeInsightItem {
  file: string;
  line: number;
  issue: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  suggestion: string;
}

export interface MissionSummary {
  id: string;
  objective: string;
  status: 'DRAFT' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  task_id?: string | null;
  created_at: string;
  updated_at: string;
  last_error?: string | null;
}

export interface MissionRecord {
  mission: {
    mission_id: string;
    objective: string;
    strategy: string;
    created_at: string;
    nodes: Array<{
      id: string;
      title: string;
      description: string;
      primary_tool?: string | null;
      fallback_tools: string[];
      tool_selection_rationale?: string;
      depends_on: string[];
      success_criteria: string;
      dry_check: Record<string, unknown>;
    }>;
  };
  status: 'DRAFT' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  task_id?: string | null;
  updated_at: string;
  last_error?: string | null;
}

export interface ToolManifest {
  name: string;
  version: string;
  input_schema: Record<string, unknown>;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  idempotent: boolean;
  timeout_seconds: number;
  retry_policy: { max_attempts: number; backoff_seconds: number };
  rollback_hint: string;
  enabled: boolean;
  optional: boolean;
  source: string;
  category: string;
  description: string;
  dependencies: Array<{ name: string; minimum_version: string; required: boolean }>;
}

export interface ToolHealth {
  name: string;
  enabled: boolean;
  circuit_open: boolean;
  cache_items: number;
  last_error_code?: string | null;
  last_error_message?: string | null;
  last_latency_ms: number;
  recent_calls: number;
}

export interface ToolExecutionResult {
  name: string;
  requested_name?: string | null;
  resolved_version?: string | null;
  success: boolean;
  output: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  cached: boolean;
  attempts: number;
  latency_ms: number;
  timestamp: string;
}

export interface ToolBatchExecutionResult {
  success: boolean;
  failed_count: number;
  success_count: number;
  results: ToolExecutionResult[];
}

export interface RollbackArtifact {
  id: string;
  task_id: string;
  action_id: string;
  action_type: string;
  backup_path?: string | null;
  target_path?: string | null;
  delete_target?: string | null;
  created_at: string;
  applied_at?: string | null;
}

export interface ExecutionReport {
  id: string;
  task_id: string;
  mission_id?: string | null;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  started_at: string;
  ended_at?: string | null;
  duration_ms: number;
  tools_used: string[];
  changed_resources: string[];
  rollback_points: string[];
  risk_summary: string;
  quota_snapshot: Record<string, unknown>;
  actions: Array<{
    action_id: string;
    action: string;
    risk_score: number;
    requires_approval: boolean;
    success: boolean;
    error?: string | null;
    changed_resources: string[];
    rollback_artifact_ids: string[];
    executed_at: string;
  }>;
  notes: string[];
}

export interface ImprovementProposalV2 {
  id: string;
  title: string;
  category: 'security' | 'performance' | 'correctness' | 'capability';
  observation: string;
  proposal: string;
  patch_path?: string | null;
  test_command: string;
  test_result: string;
  risk_score: number;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'APPLIED' | 'FAILED';
  created_at: string;
  updated_at: string;
  decided_at?: string | null;
  decision_note: string;
  metadata: Record<string, unknown>;
}

export interface ImprovementJob {
  id: string;
  focus: string;
  status: 'QUEUED' | 'RUNNING' | 'WAITING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'APPLIED' | 'FAILED' | 'CANCELLED';
  proposals: string[];
  reason: string;
  created_at: string;
  updated_at: string;
}

export interface OpsSLO {
  queue_depth: number;
  stuck_tasks: number;
  approval_backlog: number;
  quota_burn_rate: number;
}
