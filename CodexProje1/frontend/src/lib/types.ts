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
