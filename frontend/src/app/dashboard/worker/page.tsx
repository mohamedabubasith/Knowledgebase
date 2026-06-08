'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

const STAGES = ['queued', 'started', 'parsing', 'chunking', 'embedding', 'indexing', 'completed'];

const dur = (ms: number | null | undefined) =>
  ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

function StagePipeline({ current }: { current: string }) {
  const active = Math.max(0, STAGES.indexOf(current));
  return (
    <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
      {STAGES.map((s, i) => (
        <div key={s} title={s} style={{
          height: 6, flex: 1, borderRadius: 99,
          background: i <= active ? '#76b900' : '#1a280a',
          boxShadow: i === active ? '0 0 6px #76b900' : 'none',
          transition: 'all .3s',
        }} />
      ))}
    </div>
  );
}

function TimingBars({ timings }: { timings: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(timings || {}));
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      {Object.entries(timings || {}).map(([stage, value]) => (
        <div key={stage} style={{ display: 'grid', gridTemplateColumns: '68px 1fr 56px', gap: 6, fontSize: 11, alignItems: 'center' }}>
          <span style={{ color: '#5a7040' }}>{stage}</span>
          <div style={{ background: '#0e0e0e', borderRadius: 99, height: 5, border: '1px solid #1a280a' }}>
            <div style={{ height: '100%', width: `${(value / max) * 100}%`, background: '#76b900', borderRadius: 99 }} />
          </div>
          <span style={{ color: '#76b900', fontFamily: 'monospace', textAlign: 'right' }}>{dur(value)}</span>
        </div>
      ))}
    </div>
  );
}

export default function WorkerMonitor() {
  const [health, setHealth] = useState<any>({ active_jobs: [], circuit_breaker: {} });
  const [recent, setRecent] = useState<any[]>([]);
  const [dlq, setDlq] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({ by_file_type: {}, jobs_completed_per_hour: {} });

  const load = async () => {
    const since = new Date(Date.now() - 3_600_000).toISOString();
    const [h, j, d, s] = await Promise.all([
      api('admin/worker/health'),
      api(`admin/worker/job-logs?status=completed&page_size=25&date_from=${encodeURIComponent(since)}`),
      api('admin/worker/dead-letter'),
      api('admin/worker/statistics'),
    ]);
    setHealth(h);
    setRecent(j.items ?? []);
    setDlq(d);
    setStats(s);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const retry = async (id: string) => { await api(`admin/worker/dead-letter/${id}/retry`, { method: 'POST' }); load(); };
  const retryAll = async () => { await api('admin/worker/dead-letter/retry-all', { method: 'POST' }); load(); };

  const healthy = health.status === 'healthy';

  return (
    <>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 900, letterSpacing: '-.02em' }}>
          <span style={{ color: '#76b900' }}>◈</span> Worker Monitor
        </h1>
        <div style={{ color: '#5a7040', fontSize: 12, marginTop: 4, fontFamily: 'monospace' }}>
          Auto-refresh every 5s · Live processing health
        </div>
      </div>

      {/* Status cards */}
      <div className="grid-cards" style={{ marginBottom: 24 }}>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>Status</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: healthy ? '#76b900' : '#ff5555', boxShadow: `0 0 8px ${healthy ? '#76b900' : '#ff5555'}` }} />
            <span style={{ fontWeight: 800, color: healthy ? '#76b900' : '#ff5555', fontSize: 16 }}>{health.status ?? 'checking'}</span>
          </div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>Queued</div>
          <div style={{ fontSize: 32, fontWeight: 900, color: '#76b900', marginTop: 4 }}>{health.queue_length ?? 0}</div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>Active</div>
          <div style={{ fontSize: 32, fontWeight: 900, color: '#76b900', marginTop: 4 }}>{health.active_job_count ?? 0}</div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>Dead Letter</div>
          <div style={{ fontSize: 32, fontWeight: 900, color: (health.dead_letter_queue_size ?? 0) > 0 ? '#ff5555' : '#76b900', marginTop: 4 }}>
            {health.dead_letter_queue_size ?? 0}
          </div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>Circuit Breaker</div>
          <div style={{ marginTop: 8 }}>
            <span className={`badge ${health.circuit_breaker?.open ? 'badge-red' : 'badge-green'}`}>
              {health.circuit_breaker?.open ? 'OPEN' : 'Closed'}
            </span>
          </div>
        </div>
      </div>

      {/* Active jobs */}
      <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 700, marginBottom: 10 }}>
        ◈ Active Jobs
      </div>
      <div className="card" style={{ overflow: 'auto', marginBottom: 24 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Document</th>
              <th>KB</th>
              <th style={{ minWidth: 300 }}>Pipeline</th>
              <th>Stage</th>
              <th>Attempt</th>
              <th>Running</th>
            </tr>
          </thead>
          <tbody>
            {(health.active_jobs ?? []).length === 0 && (
              <tr><td colSpan={6} style={{ color: '#3d6000', textAlign: 'center', padding: 20 }}>No active jobs</td></tr>
            )}
            {(health.active_jobs ?? []).map((job: any) => (
              <tr key={job.job_id}>
                <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.document_name ?? job.document_id}</td>
                <td style={{ color: '#5a7040', fontSize: 12 }}>{job.knowledge_base_name ?? '—'}</td>
                <td><StagePipeline current={job.processing_stage} /></td>
                <td><span className="badge badge-green">{job.processing_stage}</span></td>
                <td>{job.attempt}</td>
                <td style={{ color: '#5a7040', fontSize: 12 }}>{dur(Date.now() - new Date(job.started_at).getTime())}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recent completed */}
      <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 700, marginBottom: 10 }}>
        ◈ Recently Completed
      </div>
      <div className="card" style={{ overflow: 'auto', marginBottom: 24 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Total time</th>
              <th>Stage breakdown</th>
              <th>Attempts</th>
            </tr>
          </thead>
          <tbody>
            {recent.length === 0 && (
              <tr><td colSpan={4} style={{ color: '#3d6000', textAlign: 'center', padding: 20 }}>No completed jobs in last hour</td></tr>
            )}
            {recent.map(job => (
              <tr key={job.id}>
                <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.document_name ?? job.document_id}</td>
                <td style={{ color: '#76b900', fontFamily: 'monospace', fontWeight: 700 }}>{dur(job.duration_ms)}</td>
                <td><TimingBars timings={job.stage_timings} /></td>
                <td>{job.attempt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* DLQ */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 700 }}>
          ◈ Dead Letter Queue
        </div>
        <button className="button button-danger" onClick={retryAll} disabled={dlq.length === 0}>Retry all</button>
      </div>
      <div className="card" style={{ overflow: 'auto', marginBottom: 28 }}>
        <table className="table">
          <thead>
            <tr><th>Document</th><th>Attempts</th><th>Error</th><th>Moved</th><th /></tr>
          </thead>
          <tbody>
            {dlq.length === 0 && (
              <tr><td colSpan={5} style={{ color: '#3d6000', textAlign: 'center', padding: 20 }}>Queue is empty</td></tr>
            )}
            {dlq.map(job => (
              <tr key={job.id}>
                <td>{job.document_id}</td>
                <td>{job.attempts}</td>
                <td style={{ maxWidth: 420, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: '#ff6666', fontFamily: 'monospace', fontSize: 12 }} title={job.error}>{job.error}</td>
                <td style={{ fontSize: 12, color: '#5a7040' }}>{new Date(job.moved_at).toLocaleString()}</td>
                <td><button className="button" style={{ padding: '5px 10px', fontSize: 12 }} onClick={() => retry(job.id)}>Retry</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 24h stats */}
      <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 700, marginBottom: 12 }}>
        ◈ Last 24 Hours
      </div>
      <div className="grid-cards" style={{ marginBottom: 16 }}>
        {[
          { label: 'Processed', val: stats.total_jobs_processed ?? 0 },
          { label: 'Success rate', val: `${((stats.success_rate ?? 0) * 100).toFixed(1)}%` },
          { label: 'Failure rate', val: `${((stats.failure_rate ?? 0) * 100).toFixed(1)}%` },
        ].map(({ label, val }) => (
          <div key={label} className="card" style={{ padding: '16px 20px' }}>
            <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>{label}</div>
            <div style={{ fontSize: 28, fontWeight: 900, color: '#76b900', marginTop: 6 }}>{val}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 16 }}>
        <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 14 }}>By File Type</div>
        {Object.entries(stats.by_file_type ?? {}).map(([type, value]: any) => (
          <div key={type} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1a280a', fontSize: 13 }}>
            <span style={{ color: '#5a7040', fontFamily: 'monospace' }}>{type}</span>
            <span style={{ color: '#d0e0b0' }}>
              <b style={{ color: '#76b900' }}>{dur(value.average_duration_ms)}</b>
              {' · '}{value.completed} ok · {value.failed} failed
            </span>
          </div>
        ))}
        {Object.keys(stats.by_file_type ?? {}).length === 0 && (
          <div style={{ color: '#3d6000', fontSize: 13 }}>No data yet</div>
        )}
      </div>

      <div className="card" style={{ padding: 18 }}>
        <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 14 }}>Jobs / Hour</div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end', height: 110, overflowX: 'auto' }}>
          {Object.entries(stats.jobs_completed_per_hour ?? {}).map(([hour, count]: any) => {
            const max = Math.max(1, ...Object.values(stats.jobs_completed_per_hour ?? {}).map(Number));
            return (
              <div key={hour} title={`${new Date(hour).toLocaleString()}: ${count}`} style={{
                minWidth: 20, height: `${Math.max(6, (count / max) * 100)}px`,
                background: '#76b900', borderRadius: '4px 4px 0 0',
                opacity: 0.75,
              }} />
            );
          })}
          {Object.keys(stats.jobs_completed_per_hour ?? {}).length === 0 && (
            <div style={{ color: '#3d6000', fontSize: 13 }}>No data yet</div>
          )}
        </div>
      </div>
    </>
  );
}
