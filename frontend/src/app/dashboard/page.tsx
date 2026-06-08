'use client';
import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { api } from '@/lib/api';

type GlobalStats = { knowledge_bases: number; documents: number; chunks: number; users: number; prompts_today: number };
type WorkerHealth = { status: string; queue_length: number; active_job_count: number; dead_letter_queue_size: number; circuit_breaker?: { open: boolean } };
type WorkerStats = {
  total_jobs_processed: number; success_rate: number; failure_rate: number;
  average_stage_timings: Record<string, number>;
  by_file_type: Record<string, { total: number; completed: number; failed: number; average_duration_ms: number }>;
  per_hour: Record<string, number>;
};
type Tenant = { id: string; name: string; is_active: boolean };
type TenantStats = { knowledge_bases: number; documents: number; chunks: number; prompts_today: number };

const GRN  = '#76b900';
const GRN2 = '#a8ff00';
const AMB  = '#f7c75f';
const DIM  = '#3d5a28';
const DARK = '#2d4a1e';
const PIE_COLORS = ['#76b900', '#a8ff00', '#f7c75f', '#4a9b7f', '#6e9c2a', '#c0e060', '#9fd050'];

const TT_STYLE = {
  background: 'rgba(2,6,1,0.96)',
  border: '1px solid rgba(118,185,0,0.2)',
  borderRadius: 8,
  fontSize: 12,
  color: '#b8d890',
  fontFamily: 'monospace',
};

function KpiCard({ label, value, accent = GRN }: { label: string; value: number | string; accent?: string }) {
  return (
    <div style={{
      background: 'rgba(2,6,1,0.82)',
      border: '1px solid rgba(118,185,0,0.1)',
      borderRadius: 12,
      padding: '18px 20px',
    }}>
      <div style={{ fontSize: 9, color: DARK, textTransform: 'uppercase', letterSpacing: '.15em', fontWeight: 800 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 900, color: accent, marginTop: 6, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  );
}

function ChartPanel({ title, children, style }: { title: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'rgba(2,6,1,0.82)',
      border: '1px solid rgba(118,185,0,0.1)',
      borderRadius: 12,
      padding: '18px 20px',
      ...style,
    }}>
      <div style={{ fontSize: 9, color: DARK, textTransform: 'uppercase', letterSpacing: '.15em', fontWeight: 800, marginBottom: 16 }}>{title}</div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: DARK, fontSize: 12 }}>
      {text}
    </div>
  );
}

export default function Dashboard() {
  const [now,         setNow]         = useState('');
  const [stats,       setStats]       = useState<GlobalStats | null>(null);
  const [worker,      setWorker]      = useState<WorkerHealth | null>(null);
  const [wStats,      setWStats]      = useState<WorkerStats | null>(null);
  const [tenants,     setTenants]     = useState<Tenant[]>([]);
  const [tenantData,  setTenantData]  = useState<{ name: string; docs: number; kbs: number; chunks: number }[]>([]);

  useEffect(() => {
    setNow(new Date().toUTCString().toUpperCase());
    const load = async () => {
      const [s, w, ws, ts] = await Promise.all([
        api('admin/stats').catch(() => null),
        api('admin/worker/health').catch(() => null),
        api('admin/worker/statistics').catch(() => null),
        api('admin/tenants').catch(() => []),
      ]);
      if (s)  setStats(s);
      if (w)  setWorker(w);
      if (ws) setWStats(ws);
      const tList: Tenant[] = ts ?? [];
      setTenants(tList);
      if (tList.length) {
        const td = await Promise.all(tList.map(async t => {
          const st: TenantStats = await api(`admin/tenants/${t.id}/stats`).catch(() => ({ knowledge_bases: 0, documents: 0, chunks: 0, prompts_today: 0 }));
          const name = t.name.length > 14 ? t.name.slice(0, 13) + '…' : t.name;
          return { name, docs: st.documents, kbs: st.knowledge_bases, chunks: st.chunks };
        }));
        setTenantData(td);
      }
    };
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, []);

  const perHourData = wStats?.per_hour
    ? Object.entries(wStats.per_hour)
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(-24)
        .map(([ts, count]) => ({ hour: `${new Date(ts).getHours()}h`, count }))
    : [];

  const stageData = wStats?.average_stage_timings
    ? Object.entries(wStats.average_stage_timings)
        .map(([stage, ms]) => ({ stage, ms: Math.round(ms) }))
        .sort((a, b) => b.ms - a.ms)
    : [];

  const fileTypeData = wStats?.by_file_type
    ? Object.entries(wStats.by_file_type).map(([type, v]) => ({
        type: type.replace('application/', '').replace('text/', ''),
        total: v.total,
        ok: v.completed,
        fail: v.failed,
        avgMs: v.average_duration_ms,
      }))
    : [];

  const kbPieData  = tenantData.map(t => ({ name: t.name, value: t.kbs  })).filter(d => d.value > 0);
  const docPieData = tenantData.map(t => ({ name: t.name, value: t.docs })).filter(d => d.value > 0);

  const healthy = worker?.status === 'healthy';

  return (
    <div style={{ maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ marginBottom: 26 }}>
        <div style={{ fontSize: 9, color: '#3d6000', fontFamily: 'monospace', letterSpacing: '.2em', textTransform: 'uppercase', marginBottom: 8 }}>
          ◈ ATLAS KB PLATFORM
        </div>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 900, letterSpacing: '-.03em', color: '#e0f0c0' }}>
          Platform <span style={{ color: GRN }}>Overview</span>
        </h1>
        <div style={{ color: DARK, fontSize: 11, marginTop: 5, fontFamily: 'monospace' }}>
          {now} · LOCAL AI · PRIVATE
        </div>
      </div>

      {/* Worker health strip */}
      <div style={{
        background: 'rgba(2,6,1,0.85)',
        border: `1px solid ${healthy ? 'rgba(118,185,0,0.15)' : 'rgba(255,40,40,0.22)'}`,
        borderRadius: 12,
        padding: '12px 20px',
        marginBottom: 18,
        display: 'flex',
        gap: 22,
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
            background: healthy ? GRN : '#ff4444',
            boxShadow: `0 0 8px ${healthy ? GRN : '#ff4444'}`,
          }} />
          <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.15em', textTransform: 'uppercase', color: healthy ? GRN : '#ff6666' }}>
            Worker {worker?.status || '…'}
          </span>
        </div>
        <div style={{ width: 1, height: 16, background: 'rgba(118,185,0,0.1)' }} />
        {[
          { label: 'Queue',    val: worker?.queue_length        ?? '—' },
          { label: 'Active',   val: worker?.active_job_count    ?? '—' },
          { label: 'DLQ',      val: worker?.dead_letter_queue_size ?? '—', warn: (worker?.dead_letter_queue_size ?? 0) > 0 },
          { label: 'Jobs 24h', val: wStats?.total_jobs_processed ?? '—' },
          { label: 'Success',  val: wStats ? `${(wStats.success_rate * 100).toFixed(1)}%` : '—', accent: GRN },
          { label: 'Fail',     val: wStats ? `${(wStats.failure_rate * 100).toFixed(1)}%` : '—', warn: (wStats?.failure_rate ?? 0) > 0.05 },
        ].map(({ label, val, warn, accent }) => (
          <div key={label} style={{ fontSize: 12, color: DIM }}>
            {label}: <b style={{ color: warn ? '#ff6666' : (accent ?? '#a0c870'), fontVariantNumeric: 'tabular-nums' }}>{String(val)}</b>
          </div>
        ))}
        <a href="/dashboard/worker" style={{ marginLeft: 'auto', fontSize: 10, color: GRN, textDecoration: 'none', fontWeight: 700, letterSpacing: '.1em' }}>
          WORKER DETAILS →
        </a>
      </div>

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10, marginBottom: 18 }}>
        <KpiCard label="Knowledge Bases"  value={stats?.knowledge_bases   ?? '—'} />
        <KpiCard label="Documents"        value={stats?.documents          ?? '—'} />
        <KpiCard label="Chunks Indexed"   value={stats?.chunks?.toLocaleString() ?? '—'} />
        <KpiCard label="Users"            value={stats?.users              ?? '—'} accent={GRN2} />
        <KpiCard label="Prompts Today"    value={stats?.prompts_today      ?? '—'} accent={AMB} />
        <KpiCard label="Active Tenants"   value={tenants.filter(t => t.is_active).length} accent={GRN2} />
      </div>

      {/* Charts row 1: docs per tenant + KB pie */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <ChartPanel title="Documents per Tenant">
          {tenantData.length === 0
            ? <Empty text="No tenant data" />
            : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={tenantData} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(118,185,0,0.06)" />
                  <XAxis dataKey="name" tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={TT_STYLE} cursor={{ fill: 'rgba(118,185,0,0.05)' }} />
                  <Bar dataKey="docs" fill={GRN} radius={[3,3,0,0]} name="Documents" />
                </BarChart>
              </ResponsiveContainer>
            )}
        </ChartPanel>

        <ChartPanel title="Knowledge Bases by Tenant">
          {kbPieData.length === 0
            ? <Empty text="No KB data" />
            : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={kbPieData} cx="40%" cy="50%" innerRadius={52} outerRadius={78} dataKey="value" paddingAngle={3}>
                    {kbPieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Legend iconType="circle" iconSize={8} formatter={v => <span style={{ color: DIM, fontSize: 10 }}>{v}</span>} />
                  <Tooltip contentStyle={TT_STYLE} itemStyle={{ color: '#b8d890' }} formatter={(v: number, n: string) => [v, n]} />
                </PieChart>
              </ResponsiveContainer>
            )}
        </ChartPanel>
      </div>

      {/* Charts row 2: jobs/hour + stage timings */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <ChartPanel title="Jobs Completed per Hour (24h)">
          {perHourData.length === 0
            ? <Empty text="No jobs in last 24h" />
            : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={perHourData} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(118,185,0,0.06)" />
                  <XAxis dataKey="hour" tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={TT_STYLE} cursor={{ fill: 'rgba(118,185,0,0.05)' }} />
                  <Bar dataKey="count" fill={GRN2} radius={[3,3,0,0]} name="Jobs" />
                </BarChart>
              </ResponsiveContainer>
            )}
        </ChartPanel>

        <ChartPanel title="Avg Stage Timing (ms)">
          {stageData.length === 0
            ? <Empty text="No stage timing data" />
            : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={stageData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(118,185,0,0.06)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="stage" tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} width={72} />
                  <Tooltip contentStyle={TT_STYLE} formatter={(v: number) => [`${v}ms`, 'Avg']} cursor={{ fill: 'rgba(118,185,0,0.05)' }} />
                  <Bar dataKey="ms" fill={AMB} radius={[0,3,3,0]} name="ms" />
                </BarChart>
              </ResponsiveContainer>
            )}
        </ChartPanel>
      </div>

      {/* Charts row 3: file type breakdown */}
      {fileTypeData.length > 0 && (
        <ChartPanel title="Processing by File Type">
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={fileTypeData} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(118,185,0,0.06)" />
              <XAxis dataKey="type" tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: DIM, fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={TT_STYLE} cursor={{ fill: 'rgba(118,185,0,0.05)' }} />
              <Bar dataKey="ok"   fill={GRN}      radius={[3,3,0,0]} name="Success" stackId="a" />
              <Bar dataKey="fail" fill="#ff6666"  radius={[3,3,0,0]} name="Failed"  stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      )}
    </div>
  );
}
