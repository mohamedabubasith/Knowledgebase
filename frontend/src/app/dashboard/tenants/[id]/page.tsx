'use client';
import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, BookOpen, Copy, FileText, MessageSquare, RefreshCw, RotateCcw, Trash2, Users, X, ZapOff, Zap } from 'lucide-react';
import { api } from '@/lib/api';

type Tenant  = { id: string; name: string; description: string | null; api_key_prefix: string; is_active: boolean };
type Stats   = { knowledge_bases: number; documents: number; chunks: number; prompts_today: number };
type KB      = { id: string; name: string; description: string | null; documents: number; chunks: number; created_at: string };
type Doc     = { id: string; filename: string; file_type: string; file_size: number; status: string; processing_stage: string; knowledge_base_name: string; created_at: string };
type Log     = { id: string; prompt: string; status: string; latency_ms: number; tokens_used: number; search_type: string; created_at: string };
type UsersData = { system_user: { id: string | null; email: string | null }; shared_users: { id: string; email: string; full_name: string | null; role: string; kb_name: string }[] };

const TABS = [
  { key: 'kbs',  label: 'Knowledge Bases', icon: BookOpen },
  { key: 'docs', label: 'Documents',        icon: FileText },
  { key: 'logs', label: 'Prompt Logs',      icon: MessageSquare },
  { key: 'users',label: 'Users',            icon: Users },
] as const;

type Tab = typeof TABS[number]['key'];

const STAGE_COLORS: Record<string, string> = {
  completed: '#76b900', indexed: '#76b900',
  embedding: '#a8ff00', chunking: '#f7c75f',
  parsing: '#f7c75f', queued: '#4a6a35',
  failed: '#ff6666', error: '#ff6666',
};

const TERMINAL = new Set(['completed', 'indexed', 'failed', 'error']);

function fmt(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function StatBox({ label, value, accent = '#76b900' }: { label: string; value: number | string; accent?: string }) {
  return (
    <div style={{
      background: 'rgba(0,0,0,0.55)', border: '1px solid rgba(118,185,0,0.09)',
      borderRadius: 10, padding: '16px 20px',
    }}>
      <div style={{ fontSize: 10, color: '#3d5a28', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 800 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 900, color: accent, marginTop: 6, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  );
}

function EmptyState({ icon: Icon, text }: { icon: any; text: string }) {
  return (
    <div style={{ padding: '48px 24px', textAlign: 'center', color: '#2d4a1e' }}>
      <Icon size={28} style={{ opacity: 0.25, display: 'block', margin: '0 auto 12px' }} />
      <div style={{ fontSize: 13 }}>{text}</div>
    </div>
  );
}

const glassPanel = {
  background: 'rgba(3,6,1,0.88)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(118,185,0,0.1)',
  borderRadius: 12,
  overflow: 'hidden' as const,
};

const thStyle = {
  padding: '11px 16px', textAlign: 'left' as const,
  fontSize: 10, textTransform: 'uppercase' as const, letterSpacing: '.12em',
  color: '#3d5a28', fontWeight: 800,
  borderBottom: '1px solid rgba(118,185,0,0.08)',
  background: 'rgba(118,185,0,0.02)',
};
const tdStyle = {
  padding: '11px 16px',
  borderBottom: '1px solid rgba(118,185,0,0.04)',
  fontSize: 13,
};

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [tenant,   setTenant]   = useState<Tenant | null>(null);
  const [stats,    setStats]    = useState<Stats | null>(null);
  const [kbs,      setKbs]      = useState<KB[]>([]);
  const [docs,     setDocs]     = useState<Doc[]>([]);
  const [logs,     setLogs]     = useState<Log[]>([]);
  const [users,    setUsers]    = useState<UsersData | null>(null);
  const [tab,      setTab]      = useState<Tab>('kbs');
  const [newKey,   setNewKey]   = useState<string | null>(null);
  const [copied,   setCopied]   = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    const [t, s, k, d, l, u] = await Promise.all([
      api(`admin/tenants/${id}`).catch(() => null),
      api(`admin/tenants/${id}/stats`).catch(() => null),
      api(`admin/tenants/${id}/knowledge-bases`).catch(() => []),
      api(`admin/tenants/${id}/documents`).catch(() => []),
      api(`admin/tenants/${id}/prompt-logs?limit=50`).catch(() => []),
      api(`admin/tenants/${id}/users`).catch(() => null),
    ]);
    if (t) setTenant(t);
    if (s) setStats(s);
    setKbs(k ?? []);
    setDocs(d ?? []);
    setLogs(l ?? []);
    if (u) setUsers(u);
  };

  useEffect(() => { load(); }, [id]);

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);

    const inProgress = docs.filter(d => !TERMINAL.has(d.status) && !TERMINAL.has(d.processing_stage));
    if (inProgress.length === 0) return;

    pollRef.current = setInterval(async () => {
      const qs = inProgress.map(d => `ids=${d.id}`).join('&');
      try {
        const updates: Record<string, { status: string; processing_stage: string; error_message: string | null }> =
          await api(`admin/tenants/${id}/documents/status?${qs}`);
        setDocs(prev => prev.map(d => {
          const u = updates[d.id];
          if (!u) return d;
          return { ...d, status: u.status, processing_stage: u.processing_stage };
        }));
        const stillPending = Object.values(updates).some(u => !TERMINAL.has(u.status) && !TERMINAL.has(u.processing_stage));
        if (!stillPending && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch { /* ignore poll errors */ }
    }, 3000);

    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [docs.map(d => d.id).join(','), id]);

  async function rotate() {
    if (!confirm('Rotate API key? Old key stops working immediately.')) return;
    const res = await api(`admin/tenants/${id}/rotate`, { method: 'POST' });
    setNewKey(res.api_key);
    load();
  }
  async function toggle() {
    await api(`admin/tenants/${id}/${tenant?.is_active ? 'deactivate' : 'activate'}`, { method: 'PATCH' });
    load();
  }
  async function del() {
    if (!confirm(`Delete tenant "${tenant?.name}"?\n\nThis permanently removes ALL knowledge bases, documents, vectors, and files.`)) return;
    await api(`admin/tenants/${id}`, { method: 'DELETE' });
    router.push('/dashboard');
  }
  function copy(text: string) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!tenant) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '50vh', color: '#2d4a1e', fontSize: 14 }}>
      Loading<span className="cursor" />
    </div>
  );

  const active = tenant.is_active;

  return (
    <div style={{ maxWidth: 1100 }}>
      {/* Back */}
      <button onClick={() => router.push('/dashboard')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: '#3d5a28', cursor: 'pointer', fontSize: 12, marginBottom: 22, padding: 0, fontFamily: 'inherit' }}>
        <ArrowLeft size={13} /> Back to Overview
      </button>

      {/* Tenant header */}
      <div style={{
        background: 'rgba(2,5,1,0.92)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: `1px solid ${active ? 'rgba(118,185,0,0.22)' : 'rgba(200,40,40,0.22)'}`,
        borderRadius: 16, padding: '24px 26px', marginBottom: 20, position: 'relative', overflow: 'hidden',
      }}>
        {/* Top shimmer */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 1,
          background: active
            ? 'linear-gradient(90deg, transparent, rgba(118,185,0,0.6), transparent)'
            : 'linear-gradient(90deg, transparent, rgba(255,40,40,0.4), transparent)',
        }} />
        {/* Corner glow */}
        <div style={{
          position: 'absolute', top: 0, right: 0, width: 120, height: 120,
          background: active
            ? 'radial-gradient(circle at top right, rgba(118,185,0,0.07), transparent 65%)'
            : 'radial-gradient(circle at top right, rgba(255,40,40,0.04), transparent 65%)',
          pointerEvents: 'none',
        }} />

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 900, color: '#e0f0c0', letterSpacing: '-.02em' }}>
                {tenant.name}
              </h1>
              <span style={{
                padding: '3px 10px', borderRadius: 20,
                fontSize: 10, fontWeight: 800, letterSpacing: '.12em',
                background: active ? 'rgba(118,185,0,0.1)' : 'rgba(200,30,30,0.12)',
                color: active ? '#76b900' : '#ff6666',
                border: `1px solid ${active ? 'rgba(118,185,0,0.28)' : 'rgba(200,30,30,0.3)'}`,
              }}>
                {active ? '● LIVE' : '● INACTIVE'}
              </span>
            </div>
            {tenant.description && (
              <div style={{ fontSize: 12, color: '#4a6a35', marginTop: 5 }}>{tenant.description}</div>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
              <span style={{ fontSize: 10, color: '#2d4a1e', fontFamily: 'monospace', letterSpacing: '.1em' }}>API KEY</span>
              <code style={{ fontSize: 12, color: '#3d5a28', fontFamily: 'monospace' }}>{tenant.api_key_prefix}···</code>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="button button-ghost button-sm" onClick={rotate}
              style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <RotateCcw size={12} /> Rotate Key
            </button>
            <button className="button button-ghost button-sm" onClick={toggle}
              style={{ display: 'flex', alignItems: 'center', gap: 5, color: active ? '#f7c75f' : '#76b900' }}>
              {active ? <ZapOff size={12} /> : <Zap size={12} />}
              {active ? 'Disable' : 'Enable'}
            </button>
            <button className="button button-danger button-sm" onClick={del}
              style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <Trash2 size={12} /> Delete
            </button>
          </div>
        </div>

        {/* New key */}
        {newKey && (
          <div style={{ marginTop: 18, background: 'rgba(118,185,0,0.05)', border: '1px solid rgba(118,185,0,0.22)', borderRadius: 10, padding: '12px 16px' }}>
            <div style={{ fontSize: 11, color: '#76b900', fontWeight: 700, marginBottom: 8 }}>✓ New key — copy now, shown once</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <code style={{ flex: 1, background: 'rgba(0,0,0,0.55)', padding: '8px 12px', borderRadius: 7, fontSize: 12, color: '#b0d080', fontFamily: 'monospace', border: '1px solid rgba(118,185,0,0.1)', wordBreak: 'break-all' }}>
                {newKey}
              </code>
              <button className="button button-sm" onClick={() => copy(newKey)} style={{ display: 'flex', gap: 5, alignItems: 'center', whiteSpace: 'nowrap' }}>
                <Copy size={12} /> {copied ? '✓' : 'Copy'}
              </button>
            </div>
            <button onClick={() => setNewKey(null)} style={{ marginTop: 8, background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: '#2d4a1e', fontFamily: 'inherit' }}>
              <X size={11} style={{ verticalAlign: 'middle' }} /> Dismiss
            </button>
          </div>
        )}
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginBottom: 20 }}>
          <StatBox label="Knowledge Bases" value={stats.knowledge_bases} />
          <StatBox label="Documents"       value={stats.documents} />
          <StatBox label="Chunks Indexed"  value={stats.chunks} />
          <StatBox label="Prompts Today"   value={stats.prompts_today} accent="#f7c75f" />
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 3, marginBottom: 14, flexWrap: 'wrap' }}>
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setTab(key)}
            style={{
              display: 'flex', alignItems: 'center', gap: 7,
              padding: '8px 16px',
              background: tab === key ? 'rgba(118,185,0,0.1)' : 'transparent',
              border: `1px solid ${tab === key ? 'rgba(118,185,0,0.25)' : 'rgba(118,185,0,0.07)'}`,
              borderRadius: 8, color: tab === key ? '#a8ff00' : '#3d5a28',
              cursor: 'pointer', fontSize: 12, fontWeight: tab === key ? 700 : 400,
              transition: 'all .15s', fontFamily: 'inherit',
            }}>
            <Icon size={13} /> {label}
          </button>
        ))}
        <button onClick={load}
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5, padding: '8px 12px', background: 'transparent', border: '1px solid rgba(118,185,0,0.07)', borderRadius: 8, color: '#2d4a1e', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit' }}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {/* ── KBs ── */}
      {tab === 'kbs' && (
        <div style={glassPanel}>
          {kbs.length === 0 ? <EmptyState icon={BookOpen} text="No knowledge bases yet." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                {['Name', 'Description', 'Documents', 'Chunks', 'Created'].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr></thead>
              <tbody>
                {kbs.map(kb => (
                  <tr key={kb.id}>
                    <td style={{ ...tdStyle, fontWeight: 700, color: '#b8d890' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <BookOpen size={13} style={{ color: '#76b900', flexShrink: 0 }} /> {kb.name}
                      </div>
                    </td>
                    <td style={{ ...tdStyle, color: '#3d5a28', fontSize: 12 }}>{kb.description || '—'}</td>
                    <td style={{ ...tdStyle, color: '#76b900', fontWeight: 700 }}>{kb.documents}</td>
                    <td style={{ ...tdStyle, color: '#4a6a35', fontVariantNumeric: 'tabular-nums' }}>{kb.chunks.toLocaleString()}</td>
                    <td style={{ ...tdStyle, color: '#2d4a1e', fontSize: 11, fontFamily: 'monospace' }}>{new Date(kb.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Docs ── */}
      {tab === 'docs' && (
        <div style={glassPanel}>
          {docs.length === 0 ? <EmptyState icon={FileText} text="No documents uploaded yet." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                {['File', 'Knowledge Base', 'Type', 'Size', 'Status', 'Uploaded'].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr></thead>
              <tbody>
                {docs.map(d => (
                  <tr key={d.id}>
                    <td style={{ ...tdStyle, color: '#b8d890', fontWeight: 600, maxWidth: 200 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={d.filename}>
                        <FileText size={12} style={{ color: '#4a6a35', verticalAlign: 'middle', marginRight: 6 }} />
                        {d.filename}
                      </div>
                    </td>
                    <td style={{ ...tdStyle, color: '#4a6a35', fontSize: 12 }}>{d.knowledge_base_name}</td>
                    <td style={{ ...tdStyle, color: '#2d4a1e', fontSize: 11, fontFamily: 'monospace' }}>
                      {d.file_type?.split('/')[1] ?? d.file_type}
                    </td>
                    <td style={{ ...tdStyle, color: '#3d5a28', fontSize: 12 }}>{fmt(d.file_size)}</td>
                    <td style={tdStyle}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                        padding: '2px 8px', borderRadius: 4,
                        fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase',
                        color: STAGE_COLORS[d.status] ?? STAGE_COLORS[d.processing_stage] ?? '#4a6a35',
                        background: 'rgba(0,0,0,0.3)',
                        border: `1px solid ${STAGE_COLORS[d.status] ?? '#2d4a1e'}33`,
                      }}>
                        {!TERMINAL.has(d.status) && !TERMINAL.has(d.processing_stage) && (
                          <span className="pulse-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: STAGE_COLORS[d.processing_stage] ?? '#a8ff00', display: 'inline-block', flexShrink: 0 }} />
                        )}
                        {d.processing_stage}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, color: '#2d4a1e', fontSize: 11, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      {new Date(d.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Logs ── */}
      {tab === 'logs' && (
        <div style={glassPanel}>
          {logs.length === 0 ? <EmptyState icon={MessageSquare} text="No prompt logs yet." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                {['Time', 'Prompt', 'Status', 'Search', 'Latency', 'Tokens'].map(h => <th key={h} style={thStyle}>{h}</th>)}
              </tr></thead>
              <tbody>
                {logs.map(l => (
                  <tr key={l.id}>
                    <td style={{ ...tdStyle, color: '#2d4a1e', fontSize: 11, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      {new Date(l.created_at).toLocaleTimeString()}
                    </td>
                    <td style={{ ...tdStyle, color: '#7a9a60', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={l.prompt}>
                      {l.prompt}
                    </td>
                    <td style={tdStyle}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 4,
                        fontSize: 10, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase',
                        color: l.status === 'success' ? '#76b900' : '#ff6666',
                        background: l.status === 'success' ? 'rgba(118,185,0,0.08)' : 'rgba(255,40,40,0.08)',
                        border: `1px solid ${l.status === 'success' ? 'rgba(118,185,0,0.2)' : 'rgba(255,40,40,0.2)'}`,
                      }}>
                        {l.status}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, color: '#3d5a28', fontSize: 11 }}>{l.search_type}</td>
                    <td style={{ ...tdStyle, color: '#76b900', fontFamily: 'monospace', fontWeight: 700 }}>{l.latency_ms}ms</td>
                    <td style={{ ...tdStyle, color: '#3d5a28' }}>{l.tokens_used}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Users ── */}
      {tab === 'users' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* System user */}
          <div style={glassPanel}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(118,185,0,0.08)' }}>
              <div style={{ fontSize: 10, color: '#3d5a28', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 800 }}>
                System User (API Key Identity)
              </div>
            </div>
            {users?.system_user?.email ? (
              <div style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'rgba(118,185,0,0.1)', border: '1px solid rgba(118,185,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Users size={14} style={{ color: '#76b900' }} />
                </div>
                <div>
                  <div style={{ fontSize: 13, color: '#b8d890', fontWeight: 600 }}>{users.system_user.email}</div>
                  <div style={{ fontSize: 11, color: '#3d5a28', marginTop: 2 }}>Auto-created · used for API key auth</div>
                </div>
                <span style={{ marginLeft: 'auto', padding: '2px 10px', borderRadius: 20, fontSize: 10, fontWeight: 800, letterSpacing: '.1em', background: 'rgba(118,185,0,0.08)', color: '#76b900', border: '1px solid rgba(118,185,0,0.2)' }}>
                  SYSTEM
                </span>
              </div>
            ) : (
              <div style={{ padding: '20px 16px', color: '#2d4a1e', fontSize: 13 }}>System user not found.</div>
            )}
          </div>

          {/* Shared users */}
          <div style={glassPanel}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(118,185,0,0.08)' }}>
              <div style={{ fontSize: 10, color: '#3d5a28', textTransform: 'uppercase', letterSpacing: '.12em', fontWeight: 800 }}>
                Users with KB Access ({users?.shared_users?.length ?? 0})
              </div>
            </div>
            {!users?.shared_users?.length ? (
              <EmptyState icon={Users} text="No users have been granted KB access yet. Open a KB and use the Share button." />
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>
                  {['User', 'Email', 'Knowledge Base', 'Role'].map(h => <th key={h} style={thStyle}>{h}</th>)}
                </tr></thead>
                <tbody>
                  {users.shared_users.map(u => (
                    <tr key={`${u.id}-${u.kb_name}`}>
                      <td style={{ ...tdStyle, color: '#b8d890', fontWeight: 600 }}>{u.full_name || '—'}</td>
                      <td style={{ ...tdStyle, color: '#4a6a35', fontSize: 12 }}>{u.email}</td>
                      <td style={{ ...tdStyle, color: '#4a6a35', fontSize: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <BookOpen size={11} style={{ color: '#3d5a28' }} /> {u.kb_name}
                        </div>
                      </td>
                      <td style={tdStyle}>
                        <span className={`role-chip role-${u.role}`}>{u.role}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
