import type {
  ApprovalRequest,
  ModelQuotaResponse,
  SelfImproveReport,
  TaskSummary
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

export function runSelfImprove(focus = 'all'): Promise<SelfImproveReport> {
  return json<SelfImproveReport>('/self-improve/run', {
    method: 'POST',
    body: JSON.stringify({ focus })
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

export function listSkills(): Promise<SkillManifest[]> {
  return json<SkillManifest[]>('/skills');
}

export function runSkill(skill_id: string, payload: Record<string, unknown>): Promise<SkillRunResult> {
  return json<SkillRunResult>('/skills/run', {
    method: 'POST',
    body: JSON.stringify({ skill_id, payload })
  });
}

export function searchMemory(query: string, limit = 8): Promise<MemoryEntry[]> {
  return json<MemoryEntry[]>('/memory/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit })
  });
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
