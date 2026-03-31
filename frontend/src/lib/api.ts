import type {
  ApprovalRequest,
  CodeInsightItem,
  ExecutionReport,
  ImprovementJob,
  ImprovementProposalV2,
  MissionRecord,
  MissionSummary,
  ModelQuotaResponse,
  OpsSLO,
  RollbackArtifact,
  SelfImproveReport,
  TaskSummary,
  ToolBatchExecutionResult,
  ToolExecutionResult,
  ToolHealth,
  ToolManifest
} from './types';
import type { EventMessage } from './types';

export interface SafetyStatus {
  emergency_stop: boolean;
  reason: string;
  updated_at: string;
}

export interface SkillManifest {
  skill_id: string;
  version: string;
  description: string;
  capabilities: string[];
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  entrypoint?: string | null;
  tags?: string[];
  aliases?: string[];
  source?: string;
  quality_score?: number;
  workflow?: Array<{ skill_id: string; payload: Record<string, unknown>; required: boolean }>;
}

export interface SkillRunResult {
  skill_id: string;
  success: boolean;
  output: Record<string, unknown>;
  error?: string | null;
}

export interface MemoryEntry {
  id: string;
  key: string;
  content: string;
  tags: string[];
  score: number;
  created_at: string;
  updated_at: string;
}

export interface AuthSession {
  role: 'ADMIN' | 'USER';
  token_hint: string;
  request_id: string;
}

export interface AuthBootstrapResponse {
  status: string;
  admin_token_set: boolean;
  user_token_set: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';
const TOKEN_KEY = 'jarvisx_api_token';

export function getApiToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? '';
}

export function setApiToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token.trim());
}

async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getApiToken();
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-API-Key': token } : {}),
      ...(options?.headers ?? {})
    }
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function bootstrapAuth(admin_token: string, user_token?: string): Promise<AuthBootstrapResponse> {
  return json<AuthBootstrapResponse>('/auth/bootstrap', {
    method: 'POST',
    body: JSON.stringify({ admin_token, user_token })
  });
}

export function authMe(): Promise<AuthSession> {
  return json<AuthSession>('/auth/me');
}

export function createTask(objective: string, idempotencyKey?: string): Promise<TaskSummary> {
  return json<TaskSummary>('/tasks', {
    method: 'POST',
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
    body: JSON.stringify({ objective })
  });
}

export function verifyTask(objective: string): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/tasks/verify', {
    method: 'POST',
    body: JSON.stringify({ objective })
  });
}

export function listTasks(): Promise<TaskSummary[]> {
  return json<TaskSummary[]>('/tasks');
}

export function getTaskReport(taskId: string): Promise<ExecutionReport> {
  return json<ExecutionReport>(`/tasks/${taskId}/report`);
}

export function createMission(
  objective: string,
  auto_execute = true,
  priority = 5
): Promise<MissionRecord> {
  return json<MissionRecord>('/missions', {
    method: 'POST',
    body: JSON.stringify({ objective, auto_execute, priority })
  });
}

export function listMissions(): Promise<MissionSummary[]> {
  return json<MissionSummary[]>('/missions');
}

export function getMission(missionId: string): Promise<MissionRecord> {
  return json<MissionRecord>(`/missions/${missionId}`);
}

export function getMissionReport(missionId: string): Promise<ExecutionReport> {
  return json<ExecutionReport>(`/missions/${missionId}/report`);
}

export function replanMission(missionId: string, reason = 'manual_replan'): Promise<MissionRecord> {
  return json<MissionRecord>(`/missions/${missionId}/replan`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  });
}

export function resumeTask(taskId: string, note = ''): Promise<TaskSummary> {
  return json<TaskSummary>(`/tasks/${taskId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ note })
  });
}

export function cancelTask(taskId: string, reason = 'Cancelled from dashboard'): Promise<TaskSummary> {
  return json<TaskSummary>(`/tasks/${taskId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  });
}

export function listPendingApprovals(): Promise<ApprovalRequest[]> {
  return json<ApprovalRequest[]>('/approvals/pending');
}

export function decideApproval(approvalId: string, decision: 'APPROVE' | 'REJECT'): Promise<ApprovalRequest> {
  return json<ApprovalRequest>(`/approvals/${approvalId}`, {
    method: 'POST',
    body: JSON.stringify({ decision })
  });
}

export function getModelQuotas(): Promise<ModelQuotaResponse> {
  return json<ModelQuotaResponse>('/models/quotas');
}

export function getToolsCatalog(): Promise<ToolManifest[]> {
  return json<ToolManifest[]>('/tools/catalog');
}

export function getToolsHealth(): Promise<ToolHealth[]> {
  return json<ToolHealth[]>('/tools/health');
}

export function executeTool(
  name: string,
  payload: Record<string, unknown>,
  dry_run = false,
  approved = false
): Promise<ToolExecutionResult> {
  return json<ToolExecutionResult>('/tools/execute', {
    method: 'POST',
    body: JSON.stringify({ name, payload, dry_run, approved })
  });
}

export function batchExecuteTools(
  requests: Array<{ name: string; payload?: Record<string, unknown>; dry_run?: boolean; approved?: boolean }>,
  stop_on_error = false
): Promise<ToolBatchExecutionResult> {
  return json<ToolBatchExecutionResult>('/tools/batch-execute', {
    method: 'POST',
    body: JSON.stringify({ requests, stop_on_error })
  });
}

export function getToolVersions(name: string): Promise<Array<Record<string, unknown>>> {
  return json<Array<Record<string, unknown>>>(`/tools/${encodeURIComponent(name)}/versions`);
}

export function promoteTool(name: string, version: string): Promise<{ name: string; version: string; promoted: boolean }> {
  return json<{ name: string; version: string; promoted: boolean }>(`/tools/${encodeURIComponent(name)}/promote`, {
    method: 'POST',
    body: JSON.stringify({ version })
  });
}

export function toggleTool(name: string, enabled: boolean): Promise<{ name: string; enabled: boolean }> {
  return json<{ name: string; enabled: boolean }>(`/tools/${encodeURIComponent(name)}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
}

export function runSelfImprove(focus = 'all'): Promise<SelfImproveReport> {
  return json<SelfImproveReport>('/self-improve/run', {
    method: 'POST',
    body: JSON.stringify({ focus })
  });
}

export function generateSelfImproveProposals(focus = 'all', max_items = 5): Promise<ImprovementProposalV2[]> {
  return json<ImprovementProposalV2[]>('/self-improve/proposals', {
    method: 'POST',
    body: JSON.stringify({ focus, max_items })
  });
}

export function listSelfImproveProposals(limit = 50): Promise<ImprovementProposalV2[]> {
  return json<ImprovementProposalV2[]>(`/self-improve/proposals?limit=${encodeURIComponent(String(limit))}`);
}

export function approveSelfImproveProposal(proposalId: string, note = ''): Promise<ImprovementProposalV2> {
  return json<ImprovementProposalV2>(`/self-improve/proposals/${proposalId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ note })
  });
}

export function rejectSelfImproveProposal(proposalId: string, note = ''): Promise<ImprovementProposalV2> {
  return json<ImprovementProposalV2>(`/self-improve/proposals/${proposalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note })
  });
}

export function createSelfImproveJob(focus = 'all', max_items = 5): Promise<ImprovementJob> {
  return json<ImprovementJob>('/self-improve/jobs', {
    method: 'POST',
    body: JSON.stringify({ focus, max_items })
  });
}

export function getSelfImproveJob(jobId: string): Promise<ImprovementJob> {
  return json<ImprovementJob>(`/self-improve/jobs/${jobId}`);
}

export function cancelSelfImproveJob(jobId: string, reason = 'cancelled_from_ui'): Promise<ImprovementJob> {
  return json<ImprovementJob>(`/self-improve/jobs/${jobId}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  });
}

export function transcribeVoice(path: string): Promise<{ text: string }> {
  return json<{ text: string }>('/voice/transcribe', {
    method: 'POST',
    body: JSON.stringify({ path })
  });
}

export function transcribeVoiceMic(timeout_seconds = 8, phrase_time_limit = 12): Promise<{ text: string }> {
  return json<{ text: string }>('/voice/transcribe-mic', {
    method: 'POST',
    body: JSON.stringify({ timeout_seconds, phrase_time_limit })
  });
}

export function speakVoice(text: string): Promise<{ status: string }> {
  return json<{ status: string }>('/voice/speak', {
    method: 'POST',
    body: JSON.stringify({ text })
  });
}

export function parseVoiceCommand(text: string, wake_word = 'jarvis'): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/voice/parse-command', {
    method: 'POST',
    body: JSON.stringify({ text, wake_word })
  });
}

export function executeVoiceCommand(text: string, wake_word = 'jarvis'): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/voice/execute-command', {
    method: 'POST',
    body: JSON.stringify({ text, wake_word })
  });
}

export function assistantCommand(
  text: string,
  execute = false,
  wake_word = 'jarvis'
): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/assistant/command', {
    method: 'POST',
    body: JSON.stringify({ text, execute, wake_word })
  });
}

export function ocrImage(image_path: string): Promise<{ status: string; text?: string; message?: string }> {
  return json<{ status: string; text?: string; message?: string }>('/vision/ocr', {
    method: 'POST',
    body: JSON.stringify({ image_path })
  });
}

export function ocrLayout(image_path: string): Promise<{ status: string; boxes?: Array<Record<string, unknown>>; message?: string }> {
  return json<{ status: string; boxes?: Array<Record<string, unknown>>; message?: string }>('/vision/ocr-layout', {
    method: 'POST',
    body: JSON.stringify({ image_path })
  });
}

export function analyzeVision(image_path: string): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/vision/analyze', {
    method: 'POST',
    body: JSON.stringify({ image_path })
  });
}

export function getSafetyStatus(): Promise<SafetyStatus> {
  return json<SafetyStatus>('/safety/status');
}

export function triggerEmergencyStop(reason: string): Promise<SafetyStatus> {
  return json<SafetyStatus>('/safety/emergency-stop', {
    method: 'POST',
    body: JSON.stringify({ reason })
  });
}

export function clearEmergencyStop(): Promise<SafetyStatus> {
  return json<SafetyStatus>('/safety/emergency-clear', { method: 'POST' });
}

export function previewRollback(task_id?: string | null, include_applied = false, limit = 100): Promise<RollbackArtifact[]> {
  return json<RollbackArtifact[]>('/rollback/preview', {
    method: 'POST',
    body: JSON.stringify({ task_id, include_applied, limit })
  });
}

export function applyRollback(artifact_id: string): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/rollback/apply', {
    method: 'POST',
    body: JSON.stringify({ artifact_id })
  });
}

export function listSkills(): Promise<SkillManifest[]> {
  return json<SkillManifest[]>('/skills');
}

export function searchSkills(query: string, limit = 20, include_virtual = true): Promise<SkillManifest[]> {
  return json<SkillManifest[]>('/skills/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit, include_virtual })
  });
}

export function composeSkill(
  skill_id: string,
  description: string,
  steps: Array<{ skill_id: string; payload?: Record<string, unknown>; required?: boolean }>
): Promise<SkillManifest> {
  return json<SkillManifest>('/skills/compose', {
    method: 'POST',
    body: JSON.stringify({ skill_id, description, steps })
  });
}

export function bootstrapSkills(target_count = 5000, prefix = 'autogen'): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/skills/bootstrap', {
    method: 'POST',
    body: JSON.stringify({ target_count, prefix })
  });
}

export function runSkill(skill_id: string, payload: Record<string, unknown>): Promise<SkillRunResult> {
  return json<SkillRunResult>('/skills/run', {
    method: 'POST',
    body: JSON.stringify({ skill_id, payload })
  });
}

export function getCodeInsights(max_items = 40): Promise<{ count: number; items: CodeInsightItem[] }> {
  return json<{ count: number; items: CodeInsightItem[] }>('/self-improve/code-insights', {
    method: 'POST',
    body: JSON.stringify({ max_items })
  });
}

export function searchMemory(query: string, limit = 8): Promise<MemoryEntry[]> {
  return json<MemoryEntry[]>('/memory/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit })
  });
}

export function memoryEmbed(text: string): Promise<{ vector: number[]; dimensions: number; strategy: string }> {
  return json<{ vector: number[]; dimensions: number; strategy: string }>('/memory/embed', {
    method: 'POST',
    body: JSON.stringify({ text })
  });
}

export function memoryReindex(limit = 1000): Promise<Array<{ shard: string; entries: number; avg_score: number }>> {
  return json<Array<{ shard: string; entries: number; avg_score: number }>>('/memory/reindex', {
    method: 'POST',
    body: JSON.stringify({ limit })
  });
}

export function getMemoryGraph(limit = 50): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>(`/memory/graph?limit=${encodeURIComponent(String(limit))}`);
}

export function queryMemoryGraph(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/memory/graph/query', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function getOpsSlo(): Promise<OpsSLO> {
  return json<OpsSLO>('/ops/slo');
}

export function getOpsQueue(): Promise<Array<Record<string, unknown>>> {
  return json<Array<Record<string, unknown>>>('/ops/queue');
}

export function getOpsHealthDeep(): Promise<Record<string, unknown>> {
  return json<Record<string, unknown>>('/ops/health/deep');
}

export function connectLive(onMessage: (msg: EventMessage) => void): WebSocket {
  const wsBase = API_BASE.replace(/^http/, 'ws');
  const rawToken = getApiToken();
  const protocols = rawToken ? [`token.${rawToken}`] : undefined;
  const ws = new WebSocket(`${wsBase}/ws/live`, protocols);
  ws.onopen = () => {
    ws.send('subscribe');
  };
  ws.onmessage = event => {
    try {
      onMessage(JSON.parse(event.data) as EventMessage);
    } catch {
      // Ignore malformed websocket payloads.
    }
  };
  return ws;
}
