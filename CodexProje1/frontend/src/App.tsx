import { useEffect, useMemo, useState } from 'react';
import {
  authMe,
  analyzeVision,
  bootstrapAuth,
  cancelTask,
  clearEmergencyStop,
  connectLive,
  createTask,
  decideApproval,
  getModelQuotas,
  getSafetyStatus,
  listPendingApprovals,
  listSkills,
  listTasks,
  ocrImage,
  ocrLayout,
  parseVoiceCommand,
  resumeTask,
  searchMemory,
  runSelfImprove,
  runSkill,
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
import type { ApprovalRequest, EventMessage, ModelQuotaResponse, SelfImproveReport, TaskSummary } from './lib/types';
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
  const [memoryQuery, setMemoryQuery] = useState('');
  const [memoryHits, setMemoryHits] = useState<MemoryEntry[]>([]);
  const [events, setEvents] = useState<EventMessage[]>([]);
  const [latestReport, setLatestReport] = useState<SelfImproveReport | null>(null);
  const [voiceInput, setVoiceInput] = useState('Jarvis-X status report');
  const [audioPath, setAudioPath] = useState('.jarvisx_data/input.wav');
  const [imagePath, setImagePath] = useState('.jarvisx_data/latest_screen.png');
  const [visionText, setVisionText] = useState('');
  const [visionLayout, setVisionLayout] = useState('');
  const [visionAnalysis, setVisionAnalysis] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshAll = async () => {
    try {
      const [tasksData, approvalsData, quotasData, safetyData, skillsData] = await Promise.all([
        listTasks(),
        listPendingApprovals(),
        getModelQuotas(),
        getSafetyStatus(),
        listSkills()
      ]);
      const sessionData = await authMe();
      setTasks(tasksData);
      setApprovals(approvalsData);
      setQuotas(quotasData);
      setSafety(safetyData);
      setSkills(skillsData);
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
          <div className="stack">
            {skills.length === 0 && <p className="muted">No skills found.</p>}
            {skills.map(skill => (
              <div className="skill" key={skill.skill_id}>
                <div>
                  <strong>{skill.skill_id}</strong>
                  <p>{skill.description}</p>
                  <small>{skill.version} | {skill.risk_level}</small>
                </div>
                <button onClick={() => onRunSkill(skill.skill_id)} disabled={busy}>Run</button>
              </div>
            ))}
          </div>
        </article>
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
