'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Copy, Plus, X } from 'lucide-react';
import { api } from '@/lib/api';

type Tenant = { id: string; name: string; description: string | null; api_key_prefix: string; is_active: boolean };

export default function Tenants() {
  const router = useRouter();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<{ name: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = () => api('admin/tenants').then(setTenants).catch(() => {});
  useEffect(() => { load(); }, []);

  async function create() {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const res = await api('admin/tenants', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setNewKey({ name: res.name, key: res.api_key });
      setName('');
      setDescription('');
      setShowForm(false);
      load();
    } catch (e: any) { alert(e.message); }
    finally { setCreating(false); }
  }

  function copy(text: string) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div style={{ maxWidth: 1100 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 }}>
        <div>
          <div style={{ fontSize: 10, color: '#3d5a28', fontFamily: 'monospace', letterSpacing: '.18em', textTransform: 'uppercase', marginBottom: 8 }}>
            ◈ TENANT MANAGEMENT
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 900, color: '#e0f0c0', letterSpacing: '-.02em' }}>Tenants</h1>
          <p style={{ color: '#3d5a28', fontSize: 12, margin: '6px 0 0' }}>
            Each tenant is an isolated environment with its own API key.
            Click a tenant to see all its data.
          </p>
        </div>
        <button
          className="button"
          onClick={() => setShowForm(s => !s)}
          style={{ display: 'flex', alignItems: 'center', gap: 7 }}
        >
          <Plus size={14} /> New Tenant
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div style={{
          background: 'rgba(3,7,1,0.88)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(118,185,0,0.2)',
          borderRadius: 14,
          padding: 20,
          marginBottom: 24,
        }}>
          <div style={{ fontSize: 10, color: '#3d5a28', textTransform: 'uppercase', letterSpacing: '.15em', fontWeight: 800, marginBottom: 14 }}>
            ◈ Create Tenant
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <input className="input" placeholder="Tenant name" value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && create()}
              style={{ minWidth: 200, flex: '0 0 auto' }} />
            <input className="input" placeholder="Description (optional)" value={description}
              onChange={e => setDescription(e.target.value)}
              style={{ flex: 1, minWidth: 220 }} />
            <button className="button" onClick={create} disabled={creating || !name.trim()}>
              {creating ? 'Creating…' : 'Create'}
            </button>
            <button className="button button-ghost" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* New key banner */}
      {newKey && (
        <div style={{
          background: 'rgba(3,8,1,0.9)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(118,185,0,0.3)',
          borderRadius: 14,
          padding: 20,
          marginBottom: 24,
        }}>
          <div style={{ fontWeight: 700, color: '#76b900', marginBottom: 10, fontSize: 13 }}>
            ✓ API key for <span style={{ color: '#a8ff00' }}>{newKey.name}</span> — copy now, shown only once
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <code style={{
              flex: 1, background: 'rgba(0,0,0,0.6)',
              padding: '10px 14px', borderRadius: 8,
              fontSize: 13, color: '#c0d890', fontFamily: 'monospace',
              border: '1px solid rgba(118,185,0,0.12)',
              wordBreak: 'break-all',
            }}>
              {newKey.key}
            </code>
            <button className="button" onClick={() => copy(newKey.key)} style={{ whiteSpace: 'nowrap', display: 'flex', gap: 6, alignItems: 'center' }}>
              <Copy size={13} /> {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <button onClick={() => setNewKey(null)}
            style={{ marginTop: 10, background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: '#3d5a28', display: 'flex', alignItems: 'center', gap: 5 }}>
            <X size={11} /> Dismiss
          </button>
        </div>
      )}

      {/* Tenant cards */}
      {tenants.length === 0 ? (
        <div style={{
          background: 'rgba(3,6,1,0.8)',
          border: '1px solid rgba(118,185,0,0.08)',
          borderRadius: 14,
          padding: 48,
          textAlign: 'center',
          color: '#2d4a1e',
        }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.2 }}>◈</div>
          No tenants yet. Create one above.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 14 }}>
          {tenants.map(t => (
            <div
              key={t.id}
              onClick={() => router.push(`/dashboard/tenants/${t.id}`)}
              style={{
                cursor: 'pointer',
                background: 'rgba(4,8,2,0.82)',
                backdropFilter: 'blur(14px)',
                border: `1px solid ${t.is_active ? 'rgba(118,185,0,0.15)' : 'rgba(180,30,30,0.2)'}`,
                borderRadius: 14,
                padding: '20px 22px',
                transition: 'all .2s',
                position: 'relative',
                overflow: 'hidden',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)';
                (e.currentTarget as HTMLDivElement).style.borderColor = t.is_active ? 'rgba(118,185,0,0.35)' : 'rgba(255,60,60,0.3)';
                (e.currentTarget as HTMLDivElement).style.boxShadow = t.is_active
                  ? '0 8px 32px rgba(0,0,0,0.4), 0 0 20px rgba(118,185,0,0.08)'
                  : '0 8px 32px rgba(0,0,0,0.4)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.transform = 'translateY(0)';
                (e.currentTarget as HTMLDivElement).style.borderColor = t.is_active ? 'rgba(118,185,0,0.15)' : 'rgba(180,30,30,0.2)';
                (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 800, fontSize: 15, color: '#d0e8a8', marginBottom: 4 }}>{t.name}</div>
                  {t.description && <div style={{ fontSize: 12, color: '#4a6a35', marginBottom: 6 }}>{t.description}</div>}
                  <code style={{ fontSize: 10, color: '#2d4a1e', fontFamily: 'monospace', letterSpacing: '.08em' }}>
                    {t.api_key_prefix}···
                  </code>
                </div>
                <div style={{
                  padding: '3px 9px', borderRadius: 20,
                  background: t.is_active ? 'rgba(118,185,0,0.1)' : 'rgba(180,30,30,0.1)',
                  border: `1px solid ${t.is_active ? 'rgba(118,185,0,0.25)' : 'rgba(180,30,30,0.25)'}`,
                  fontSize: 10, fontWeight: 800, letterSpacing: '.1em',
                  color: t.is_active ? '#76b900' : '#ff6666',
                }}>
                  {t.is_active ? 'LIVE' : 'OFF'}
                </div>
              </div>
              <div style={{ marginTop: 14, fontSize: 10, color: '#2d4a1e', letterSpacing: '.08em', textAlign: 'right' }}>
                VIEW DETAILS →
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Usage reference */}
      <div style={{
        marginTop: 28,
        background: 'rgba(2,5,1,0.8)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(118,185,0,0.07)',
        borderRadius: 12,
        padding: 20,
      }}>
        <div style={{ fontSize: 10, color: '#3d5a28', textTransform: 'uppercase', letterSpacing: '.15em', fontWeight: 800, marginBottom: 14 }}>
          ◈ How to use from another app
        </div>
        <pre style={{
          margin: 0, padding: '14px 16px',
          background: 'rgba(0,0,0,0.6)',
          border: '1px solid rgba(118,185,0,0.07)',
          borderRadius: 8,
          fontSize: 12, color: '#4a6a35', fontFamily: 'monospace', overflowX: 'auto',
        }}>{`# Pass API key in every request — no login needed
X-API-Key: kb_<your-tenant-key>

# Create KB, upload docs, run queries — all scoped to your tenant
curl -X POST https://host/api/v1/query/search \\
  -H "X-API-Key: kb_..." \\
  -H "Content-Type: application/json" \\
  -d '{"knowledge_base_id": "<id>", "prompt": "your question"}'`}</pre>
      </div>
    </div>
  );
}
