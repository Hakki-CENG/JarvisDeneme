import { useEffect, useMemo, useState } from 'react';
import {
  applyRollback,
  approveSelfImproveProposal,
  assistantCommand,
  authMe,
  analyzeVision,
  bootstrapSkills,
  bootstrapAuth,
  cancelTask,
  clearEmergencyStop,
  connectLive,
  createMission,
  createSelfImproveJob,
  createTask,
  decideApproval,
  executeVoiceCommand,
  executeTool,
  generateSelfImproveProposals,
  getModelQuotas,
  getOpsQueue,
  getOpsSlo,
  getMissionReport,
  getToolsCatalog,
  getToolsHealth,
  getTaskReport,
  getCodeInsights,
  getSafetyStatus,
  listMissions,
  listSelfImproveProposals,
  listPendingApprovals,
  listSkills,
  listTasks,
  ocrImage,
  ocrLayout,
  parseVoiceCommand,
  previewRollback,
  rejectSelfImproveProposal,
  replanMission,
  resumeTask,
  searchMemory,
  runSelfImprove,
  runSkill,
  searchSkills,
  setApiToken,
  speakVoice,
  verifyTask,
  transcribeVoice,
  transcribeVoiceMic,
  triggerEmergencyStop,
  getApiToken,
  type AuthSession,
  type MemoryEntry,
  type SafetyStatus,
  type SkillManifest
} from './lib/api';
import type {
  ApprovalRequest,
  EventMessage,
  ExecutionReport,
  ImprovementProposalV2,
  MissionSummary,
  ModelQuotaResponse,
  OpsSLO,
  RollbackArtifact,
  SelfImproveReport,
  TaskSummary,
  ToolHealth,
  ToolManifest
} from './lib/types';
import './styles/app.css';

function formatDate(value?: string | null): string {
  if (!value) {
    return '-';
  }
  const d = new Date(value);
  return d.toLocaleString();
}

export default function App() {
  const [objective, setObjective] = useState('');
  const [apiToken, setApiTokenState] = useState(getApiToken());
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [session, setSession] = useState<AuthSession | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [quotas, setQuotas] = useState<ModelQuotaResponse | null>(null);
  const [safety, setSafety] = useState<SafetyStatus | null>(null);
  const [skills, setSkills] = useState<SkillManifest[]>([]);
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [toolCatalog, setToolCatalog] = useState<ToolManifest[]>([]);
  const [toolHealth, setToolHealth] = useState<ToolHealth[]>([]);
  const [toolName, setToolName] = useState('wikipedia.search');
  const [toolPayload, setToolPayload] = useState('{\"query\":\"latest ai agents\"}');
  const [toolResult, setToolResult] = useState<string>('');
  const [rollbackArtifacts, setRollbackArtifacts] = useState<RollbackArtifact[]>([]);
  const [proposals, setProposals] = useState<ImprovementProposalV2[]>([]);
  const [opsSlo, setOpsSlo] = useState<OpsSLO | null>(null);
  const [opsQueue, setOpsQueue] = useState<Array<Record<string, unknown>>>([]);
  const [selectedTaskReport, setSelectedTaskReport] = useState<ExecutionReport | null>(null);
  const [memoryQuery, setMemoryQuery] = useState('');
  const [memoryHits, setMemoryHits] = useState<MemoryEntry[]>([]);
  const [events, setEvents] = useState<EventMessage[]>([]);
  const [latestReport, setLatestReport] = useState<SelfImproveReport | null>(null);
  const [codeInsights, setCodeInsights] = useState<Array<{ file: string; line: number; issue: string; severity: string; suggestion: string }>>([]);
  const [voiceInput, setVoiceInput] = useState('Jarvis-X status report');
  const [audioPath, setAudioPath] = useState('.jarvisx_data/input.wav');
  const [imagePath, setImagePath] = useState('.jarvisx_data/latest_screen.png');
  const [visionText, setVisionText] = useState('');
  const [visionLayout, setVisionLayout] = useState('');
  const [visionAnalysis, setVisionAnalysis] = useState('');
  const [skillSearchQuery, setSkillSearchQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshAll = async () => {
    try {
      const [
        tasksData,
        approvalsData,
        quotasData,
        safetyData,
        skillsData,
        missionsData,
        toolsData,
        toolHealthData,
        rollbackData,
        proposalData,
        opsSloData,
        opsQueueData
      ] = await Promise.all([
        listTasks(),
        listPendingApprovals(),
        getModelQuotas(),
        getSafetyStatus(),
        listSkills(),
        listMissions(),
        getToolsCatalog(),
        getToolsHealth(),
        previewRollback(undefined, false, 40),
        listSelfImproveProposals(40),
        getOpsSlo(),
        getOpsQueue()
      ]);
      const sessionData = await authMe();
      setTasks(tasksData);
      setApprovals(approvalsData);
      setQuotas(quotasData);
      setSafety(safetyData);
      setSkills(skillsData);
      setMissions(missionsData);
      setToolCatalog(toolsData);
      setToolHealth(toolHealthData);
      setRollbackArtifacts(rollbackData);
      setProposals(proposalData);
      setOpsSlo(opsSloData);
      setOpsQueue(opsQueueData);
      setSession(sessionData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    }
  };

  useEffect(() => {
    refreshAll();
    const timer = window.setInterval(refreshAll, 6000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!apiToken) {
      return;
    }
    const ws = connectLive((message: EventMessage) => {
      setEvents(prev => [message, ...prev].slice(0, 120));
      if (
        message.type === 'task_status' ||
        message.type === 'task_completed' ||
        message.type === 'task_failed' ||
        message.type === 'approval_requested' ||
        message.type === 'approval_decided'
      ) {
        refreshAll();
      }
    });
    return () => ws.close();
  }, [apiToken]);

  const stats = useMemo(() => {
    return {
      total: tasks.length,
      running: tasks.filter(t => t.status === 'RUNNING').length,
      waitingApproval: tasks.filter(t => t.status === 'WAITING_APPROVAL').length,
      failed: tasks.filter(t => t.status === 'FAILED').length,
      cancelled: tasks.filter(t => t.status === 'CANCELLED').length
    };
  }, [tasks]);

  const onCreateTask = async () => {
    if (!objective.trim()) {
      return;
    }
    setBusy(true);
    try {
      const key = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Date.now());
      await createTask(objective.trim(), key);
      setObjective('');
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Task creation failed');
    } finally {
      setBusy(false);
    }
  };

  const onCreateMission = async () => {
    if (!objective.trim()) {
      return;
    }
    setBusy(true);
    try {
      await createMission(objective.trim(), true, 5);
      setObjective('');
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mission creation failed');
    } finally {
      setBusy(false);
    }
  };

  const onVerifyTask = async () => {
    if (!objective.trim()) {
      return;
    }
    setBusy(true);
    try {
      const report = await verifyTask(objective.trim());
      setEvents(prev => [
        {
          type: 'task_verification',
          payload: report,
          created_at: new Date().toISOString()
        },
        ...prev
      ]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Task verification failed');
    } finally {
      setBusy(false);
    }
  };

  const onSearchMemory = async () => {
    try {
      const hits = await searchMemory(memoryQuery.trim() || objective.trim(), 10);
      setMemoryHits(hits);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Memory search failed');
    }
  };

  const onDecision = async (approvalId: string, decision: 'APPROVE' | 'REJECT') => {
    try {
      await decideApproval(approvalId, decision);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approval update failed');
    }
  };

  const onSelfImprove = async () => {
    setBusy(true);
    try {
      const report = await runSelfImprove('all');
      setLatestReport(report);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Self improvement run failed');
    } finally {
      setBusy(false);
    }
  };

  const onGenerateProposals = async () => {
    setBusy(true);
    try {
      const generated = await generateSelfImproveProposals('all', 8);
      setProposals(generated);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Proposal generation failed');
    } finally {
      setBusy(false);
    }
  };

  const onCreateImproveJob = async () => {
    setBusy(true);
    try {
      const job = await createSelfImproveJob('all', 6);
      setEvents(prev => [
        { type: 'self_improve_job_created', payload: job as unknown as Record<string, unknown>, created_at: new Date().toISOString() },
        ...prev
      ]);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Self-improve job creation failed');
    } finally {
      setBusy(false);
    }
  };

  const onProposalDecision = async (proposalId: string, approve: boolean) => {
    try {
      if (approve) {
        await approveSelfImproveProposal(proposalId, 'approved from dashboard');
      } else {
        await rejectSelfImproveProposal(proposalId, 'rejected from dashboard');
      }
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Proposal decision failed');
    }
  };

  const onEmergencyToggle = async () => {
    if (!safety) {
      return;
    }
    try {
      const next = safety.emergency_stop
        ? await clearEmergencyStop()
        : await triggerEmergencyStop('Manual emergency stop from UI');
      setSafety(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Safety update failed');
    }
  };

  const onRunSkill = async (skillId: string) => {
    setBusy(true);
    try {
      const result = await runSkill(skillId, { source: 'ui', at: new Date().toISOString() });
      setEvents(prev => [
        {
          type: 'skill_run_result',
          payload: result as unknown as Record<string, unknown>,
          created_at: new Date().toISOString()
        },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Skill run failed');
    } finally {
      setBusy(false);
    }
  };

  const onSearchSkills = async () => {
    try {
      const hits = await searchSkills(skillSearchQuery.trim() || 'workflow', 30, true);
      setSkills(hits);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Skill search failed');
    }
  };

  const onExecuteTool = async (dry_run: boolean) => {
    setBusy(true);
    try {
      const payload = toolPayload.trim() ? JSON.parse(toolPayload) : {};
      const result = await executeTool(toolName.trim(), payload, dry_run, !dry_run);
      setToolResult(JSON.stringify(result, null, 2));
      setEvents(prev => [
        { type: dry_run ? 'tool_dry_run' : 'tool_execute', payload: result as unknown as Record<string, unknown>, created_at: new Date().toISOString() },
        ...prev
      ]);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Tool execution failed');
    } finally {
      setBusy(false);
    }
  };

  const onRefreshRollback = async () => {
    try {
      const artifacts = await previewRollback(undefined, false, 100);
      setRollbackArtifacts(artifacts);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rollback preview failed');
    }
  };

  const onApplyRollback = async (artifactId: string) => {
    try {
      await applyRollback(artifactId);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rollback apply failed');
    }
  };

  const onLoadTaskReport = async (taskId: string) => {
    try {
      const report = await getTaskReport(taskId);
      setSelectedTaskReport(report);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Task report load failed');
    }
  };

  const onMissionReplan = async (missionId: string) => {
    try {
      await replanMission(missionId, 'dashboard_replan');
      const report = await getMissionReport(missionId).catch(() => null);
      if (report) {
        setSelectedTaskReport(report);
      }
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mission replan failed');
    }
  };

  const onBootstrapSkills = async () => {
    setBusy(true);
    try {
      const result = await bootstrapSkills(5000, 'jarvis');
      setEvents(prev => [
        { type: 'skills_bootstrap', payload: result, created_at: new Date().toISOString() },
        ...prev
      ]);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Skill bootstrap failed');
    } finally {
      setBusy(false);
    }
  };

  const onCodeInsights = async () => {
    try {
      const result = await getCodeInsights(20);
      setCodeInsights(result.items);
      setEvents(prev => [
        { type: 'code_insights', payload: result as unknown as Record<string, unknown>, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Code insights failed');
    }
  };

  const onResumeTask = async (taskId: string) => {
    try {
      await resumeTask(taskId, 'resume from dashboard');
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Task resume failed');
    }
  };

  const onCancelTask = async (taskId: string) => {
    try {
      await cancelTask(taskId, 'cancelled from dashboard');
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Task cancel failed');
    }
  };

  const onSpeak = async () => {
    try {
      await speakVoice(voiceInput);
      setEvents(prev => [
        { type: 'voice_speak', payload: { text: voiceInput }, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice speak failed');
    }
  };

  const onTranscribe = async () => {
    try {
      const result = await transcribeVoice(audioPath);
      setEvents(prev => [
        { type: 'voice_transcribe', payload: result as unknown as Record<string, unknown>, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice transcription failed');
    }
  };

  const onTranscribeMic = async () => {
    try {
      const result = await transcribeVoiceMic();
      setEvents(prev => [
        { type: 'voice_transcribe_mic', payload: result as unknown as Record<string, unknown>, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Microphone transcription failed');
    }
  };

  const onParseVoiceCommand = async () => {
    try {
      const parsed = await parseVoiceCommand(voiceInput, 'jarvis');
      setEvents(prev => [
        { type: 'voice_command_parsed', payload: parsed, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice command parse failed');
    }
  };

  const onExecuteVoiceCommand = async () => {
    try {
      const result = await executeVoiceCommand(voiceInput, 'jarvis');
      setEvents(prev => [
        { type: 'voice_command_executed', payload: result, created_at: new Date().toISOString() },
        ...prev
      ]);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Voice command execution failed');
    }
  };

  const onAssistantPlan = async () => {
    try {
      const result = await assistantCommand(voiceInput, false, 'jarvis');
      setEvents(prev => [
        { type: 'assistant_command_plan', payload: result, created_at: new Date().toISOString() },
        ...prev
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Assistant plan failed');
    }
  };

  const onAssistantExecute = async () => {
    try {
      const result = await assistantCommand(voiceInput, true, 'jarvis');
      setEvents(prev => [
        { type: 'assistant_command_execute', payload: result, created_at: new Date().toISOString() },
        ...prev
      ]);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Assistant execute failed');
    }
  };

  const onVision = async () => {
    try {
      const result = await ocrImage(imagePath);
      setVisionText(result.text ?? result.message ?? '');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Vision OCR failed');
    }
  };

  const onVisionLayout = async () => {
    try {
      const result = await ocrLayout(imagePath);
      setVisionLayout(JSON.stringify(result.boxes ?? [], null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Vision layout OCR failed');
    }
  };

  const onVisionAnalyze = async () => {
    try {
      const result = await analyzeVision(imagePath);
      setVisionAnalysis(JSON.stringify(result, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Vision analyze failed');
    }
  };

  const onSaveToken = async () => {
    setApiToken(apiToken);
    await refreshAll();
  };

  const onBootstrap = async () => {
    try {
      const token = bootstrapToken.trim();
      if (!token) {
        return;
      }
      await bootstrapAuth(token);
      setApiToken(token);
      setApiTokenState(token);
      await refreshAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bootstrap failed');
    }
  };

  return (
    <div className="layout">
      <header className="hero">
        <div>
          <p className="eyebrow">Jarvis-X Control Deck</p>
          <h1>Full Desktop Autonomy with Approval Guardrails</h1>
          <p className="muted">Multi-agent reasoning, desktop action engine, quota-aware continuity, self-improvement loop.</p>
          <p className="muted">Session: {session?.role ?? 'UNAUTHENTICATED'} {session ? `(${session.token_hint})` : ''}</p>
        </div>
        <div className="hero-actions">
          <button className={`danger ${safety?.emergency_stop ? 'active' : ''}`} onClick={onEmergencyToggle}>
            {safety?.emergency_stop ? 'Emergency Stop Active' : 'Trigger Emergency Stop'}
          </button>
          <button onClick={onSelfImprove} disabled={busy}>Run Self-Improve</button>
        </div>
      </header>

      <section className="grid two">
        <article className="card">
          <h2>Authentication</h2>
          <label className="muted">API Token</label>
          <input value={apiToken} onChange={e => setApiTokenState(e.target.value)} placeholder="X-API-Key token" />
          <div className="row">
            <button onClick={onSaveToken}>Save Token</button>
          </div>
          <small>If first setup, read `backend/.jarvisx_data/INITIAL_ADMIN_TOKEN.txt` and paste here.</small>
        </article>
        <article className="card">
          <h2>Bootstrap Tokens</h2>
          <label className="muted">New Admin Token</label>
          <input value={bootstrapToken} onChange={e => setBootstrapToken(e.target.value)} placeholder="Enter admin token (24+ chars)" />
          <div className="row">
            <button onClick={onBootstrap}>Bootstrap</button>
          </div>
          <small>User token backend tarafından otomatik güvenli şekilde üretilir.</small>
        </article>
      </section>

      <section className="grid four">
        <article className="card metric"><span>Total Tasks</span><strong>{stats.total}</strong></article>
        <article className="card metric"><span>Running</span><strong>{stats.running}</strong></article>
        <article className="card metric"><span>Waiting Approval</span><strong>{stats.waitingApproval}</strong></article>
        <article className="card metric"><span>Failed/Cancelled</span><strong>{stats.failed + stats.cancelled}</strong></article>
      </section>

      <section className="grid four">
        <article className="card metric"><span>Queue Depth</span><strong>{opsSlo?.queue_depth ?? '-'}</strong></article>
        <article className="card metric"><span>Stuck Tasks</span><strong>{opsSlo?.stuck_tasks ?? '-'}</strong></article>
        <article className="card metric"><span>Approval Backlog</span><strong>{opsSlo?.approval_backlog ?? '-'}</strong></article>
        <article className="card metric"><span>Quota Burn</span><strong>{typeof opsSlo?.quota_burn_rate === 'number' ? `${(opsSlo.quota_burn_rate * 100).toFixed(1)}%` : '-'}</strong></article>
      </section>

      <section className="grid two">
        <article className="card composer">
          <h2>Launch Mission</h2>
          <textarea
            value={objective}
            onChange={e => setObjective(e.target.value)}
            placeholder="Example: Chrome aç, dashboard'a gir, son raporu oku, özet dosyası oluştur"
          />
          <div className="row">
            <button onClick={onCreateTask} disabled={busy || !objective.trim()}>Create Task</button>
            <button onClick={onCreateMission} disabled={busy || !objective.trim()}>Create Mission</button>
            <button className="ghost" onClick={onVerifyTask} disabled={busy || !objective.trim()}>Verify Plan</button>
            <button className="ghost" onClick={refreshAll}>Refresh</button>
          </div>
          {error && <p className="error">{error}</p>}
        </article>

        <article className="card">
          <h2>Model Quotas</h2>
          <p className="muted">Primary: {quotas?.primary ?? '-'} | Selected: {quotas?.selected_provider ?? 'none'}</p>
          <div className="quota-list">
            {(quotas?.providers ?? []).map(provider => (
              <div key={provider.provider} className="quota-item">
                <span>{provider.provider}</span>
                <strong>{provider.remaining_requests}</strong>
                <small>reset {formatDate(provider.reset_at ?? null)}</small>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid two">
        <article className="card">
          <h2>Pending Approvals</h2>
          <div className="stack">
            {approvals.length === 0 && <p className="muted">No pending approvals.</p>}
            {approvals.map(item => (
              <div className="approval" key={item.id}>
                <div>
                  <strong>{item.action}</strong>
                  <p>{item.reason}</p>
                  <small>{item.id}</small>
                </div>
                <div className="row">
                  <button onClick={() => onDecision(item.id, 'APPROVE')}>Approve</button>
                  <button className="ghost" onClick={() => onDecision(item.id, 'REJECT')}>Reject</button>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <h2>Installed Skills</h2>
          <div className="row">
            <input value={skillSearchQuery} onChange={e => setSkillSearchQuery(e.target.value)} placeholder="Search skills" />
            <button className="ghost" onClick={onSearchSkills}>Search</button>
            <button className="ghost" onClick={onBootstrapSkills} disabled={busy}>Scale Catalog</button>
            <button className="ghost" onClick={onCodeInsights}>Code Insights</button>
          </div>
          <div className="stack">
            {skills.length === 0 && <p className="muted">No skills found.</p>}
            {skills.map(skill => (
              <div className="skill" key={skill.skill_id}>
                <div>
                  <strong>{skill.skill_id}</strong>
                  <p>{skill.description}</p>
                  <small>{skill.version} | {skill.risk_level} | {skill.source ?? 'local'}</small>
                </div>
                <button onClick={() => onRunSkill(skill.skill_id)} disabled={busy}>Run</button>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid two">
        <article className="card">
          <h2>Mission Graph Viewer</h2>
          <div className="stack">
            {missions.length === 0 && <p className="muted">No missions created yet.</p>}
            {missions.map(mission => (
              <div className="task" key={mission.id}>
                <strong>{mission.status}</strong>
                <p>{mission.objective}</p>
                <small>{mission.id}</small>
                <small>task: {mission.task_id || '-'}</small>
                <div className="row">
                  <button className="ghost" onClick={() => onMissionReplan(mission.id)}>Replan</button>
                  {mission.task_id && <button className="ghost" onClick={() => onLoadTaskReport(mission.task_id!)}>Report</button>}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <h2>Tool Catalog & Health</h2>
          <label className="muted">Tool Name</label>
          <input value={toolName} onChange={e => setToolName(e.target.value)} placeholder="wikipedia.search" />
          <label className="muted">Payload (JSON)</label>
          <textarea value={toolPayload} onChange={e => setToolPayload(e.target.value)} />
          <div className="row">
            <button onClick={() => onExecuteTool(true)} disabled={busy}>Dry-Run</button>
            <button onClick={() => onExecuteTool(false)} disabled={busy}>Execute</button>
          </div>
          <div className="event">
            <strong>Execution Result</strong>
            <pre>{toolResult || 'No tool run yet.'}</pre>
          </div>
          <div className="stack">
            {toolHealth.slice(0, 8).map(item => (
              <div key={item.name} className="event">
                <strong>{item.name}</strong>
                <small>enabled={String(item.enabled)} circuit_open={String(item.circuit_open)} calls={item.recent_calls}</small>
              </div>
            ))}
            <small className="muted">Catalog size: {toolCatalog.length}</small>
          </div>
        </article>
      </section>

      <section className="card">
        <h2>Code Insights</h2>
        <div className="stack">
          {codeInsights.length === 0 && <p className="muted">No code insights loaded yet.</p>}
          {codeInsights.map((item, idx) => (
            <div key={`${item.file}-${item.line}-${idx}`} className="event">
              <strong>{item.severity} | {item.issue}</strong>
              <small>{item.file}:{item.line}</small>
              <p>{item.suggestion}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid two">
        <article className="card">
          <h2>Rollback Center</h2>
          <div className="row">
            <button className="ghost" onClick={onRefreshRollback}>Refresh Rollbacks</button>
          </div>
          <div className="stack">
            {rollbackArtifacts.length === 0 && <p className="muted">No rollback artifacts.</p>}
            {rollbackArtifacts.map(item => (
              <div className="event" key={item.id}>
                <strong>{item.action_type}</strong>
                <small>{item.id}</small>
                <small>task={item.task_id}</small>
                <small>target={item.target_path || item.delete_target || '-'}</small>
                <button onClick={() => onApplyRollback(item.id)}>Apply</button>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <h2>Self-Improve Proposals</h2>
          <div className="row">
            <button onClick={onGenerateProposals} disabled={busy}>Generate Proposals</button>
            <button className="ghost" onClick={onCreateImproveJob} disabled={busy}>Create Improvement Job</button>
          </div>
          <div className="stack">
            {proposals.length === 0 && <p className="muted">No proposals loaded.</p>}
            {proposals.map(item => (
              <div key={item.id} className="event">
                <strong>{item.category.toUpperCase()} | {item.status}</strong>
                <p>{item.title}</p>
                <small>{item.observation}</small>
                <small>risk={item.risk_score} test={item.test_result || '-'}</small>
                <div className="row">
                  <button onClick={() => onProposalDecision(item.id, true)}>Approve</button>
                  <button className="ghost" onClick={() => onProposalDecision(item.id, false)}>Reject</button>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="card">
        <h2>Ops Queue</h2>
        <div className="stack">
          {opsQueue.length === 0 && <p className="muted">Queue empty.</p>}
          {opsQueue.slice(0, 12).map((item, idx) => (
            <div key={`${item.task_id ?? idx}`} className="event">
              <strong>{String(item.task_id ?? '-')}</strong>
              <small>priority={String(item.priority ?? '-')} age={Math.round(Number(item.age_seconds ?? 0))}s</small>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Long-Term Memory</h2>
        <div className="row">
          <input value={memoryQuery} onChange={e => setMemoryQuery(e.target.value)} placeholder="Search memory" />
          <button className="ghost" onClick={onSearchMemory}>Search</button>
        </div>
        <div className="stack">
          {memoryHits.length === 0 && <p className="muted">No memory hits yet.</p>}
          {memoryHits.map(item => (
            <div key={item.id} className="event">
              <strong>{item.key}</strong>
              <small>{item.tags.join(', ') || '-'}</small>
              <pre>{item.content}</pre>
            </div>
          ))}
        </div>
      </section>

      <section className="grid two">
        <article className="card">
          <h2>Task Stream</h2>
          <div className="stack tasks">
            {tasks.length === 0 && <p className="muted">No tasks yet.</p>}
            {tasks.map(task => (
              <div key={task.id} className={`task status-${task.status.toLowerCase()}`}>
                <strong>{task.status}</strong>
                <p>{task.objective}</p>
                <small>{task.id}</small>
                <small>updated {formatDate(task.updated_at)}</small>
                {task.last_error && <small className="error">{task.last_error}</small>}
                <div className="row">
                  <button className="ghost" onClick={() => onLoadTaskReport(task.id)}>Report</button>
                </div>
                {(task.status === 'FAILED' || task.status === 'PAUSED_QUOTA' || task.status === 'CANCELLED') && (
                  <div className="row">
                    <button onClick={() => onResumeTask(task.id)}>Resume</button>
                  </div>
                )}
                {(task.status === 'RUNNING' || task.status === 'WAITING_APPROVAL') && (
                  <div className="row">
                    <button className="ghost" onClick={() => onCancelTask(task.id)}>Cancel</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <h2>Live Event Feed</h2>
          <div className="stack events">
            {events.length === 0 && <p className="muted">Waiting for events...</p>}
            {events.map((event, idx) => (
              <div key={`${event.created_at}-${idx}`} className="event">
                <strong>{event.type}</strong>
                <small>{formatDate(event.created_at)}</small>
                <pre>{JSON.stringify(event.payload, null, 2)}</pre>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid two">
        <article className="card">
          <h2>Voice Console</h2>
          <label className="muted">Speak Text</label>
          <textarea value={voiceInput} onChange={e => setVoiceInput(e.target.value)} />
          <div className="row">
            <button onClick={onSpeak}>Speak</button>
            <button className="ghost" onClick={onParseVoiceCommand}>Parse Command</button>
            <button className="ghost" onClick={onExecuteVoiceCommand}>Execute Command</button>
          </div>
          <div className="row">
            <button className="ghost" onClick={onAssistantPlan}>Assistant Plan</button>
            <button onClick={onAssistantExecute}>Assistant Execute</button>
          </div>
          <label className="muted">Transcribe Audio File Path</label>
          <input value={audioPath} onChange={e => setAudioPath(e.target.value)} />
          <div className="row">
            <button onClick={onTranscribe}>Transcribe</button>
            <button className="ghost" onClick={onTranscribeMic}>Transcribe Mic</button>
          </div>
        </article>

        <article className="card">
          <h2>Vision Console</h2>
          <label className="muted">Image Path</label>
          <input value={imagePath} onChange={e => setImagePath(e.target.value)} />
          <div className="row">
            <button onClick={onVision}>Run OCR</button>
            <button className="ghost" onClick={onVisionLayout}>Layout OCR</button>
            <button className="ghost" onClick={onVisionAnalyze}>Analyze Scene</button>
          </div>
          <div className="event">
            <strong>OCR Output</strong>
            <pre>{visionText || 'No OCR output yet.'}</pre>
          </div>
          <div className="event">
            <strong>OCR Layout Boxes</strong>
            <pre>{visionLayout || 'No OCR layout yet.'}</pre>
          </div>
          <div className="event">
            <strong>Vision Analysis</strong>
            <pre>{visionAnalysis || 'No vision analysis yet.'}</pre>
          </div>
        </article>
      </section>

      {selectedTaskReport && (
        <section className="card">
          <h2>Execution Report</h2>
          <p className="muted">
            Task: {selectedTaskReport.task_id} | Status: {selectedTaskReport.status} | Duration: {selectedTaskReport.duration_ms}ms
          </p>
          <p>{selectedTaskReport.risk_summary}</p>
          <div className="event">
            <strong>Tools Used</strong>
            <pre>{JSON.stringify(selectedTaskReport.tools_used, null, 2)}</pre>
          </div>
          <div className="event">
            <strong>Changed Resources</strong>
            <pre>{JSON.stringify(selectedTaskReport.changed_resources, null, 2)}</pre>
          </div>
          <div className="event">
            <strong>Rollback Points</strong>
            <pre>{JSON.stringify(selectedTaskReport.rollback_points, null, 2)}</pre>
          </div>
        </section>
      )}

      {latestReport && (
        <section className="card">
          <h2>Last Self-Improve Report</h2>
          <p className="muted">Status: {latestReport.status} | Tests: {latestReport.tests_passed ? 'PASS' : 'FAIL'}</p>
          <p>{latestReport.risk_summary}</p>
          <div className="stack">
            {latestReport.findings.map(finding => (
              <div key={finding.id} className="event">
                <strong>{finding.gap}</strong>
                <p>{finding.proposal}</p>
                <small>{finding.expected_impact}</small>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
