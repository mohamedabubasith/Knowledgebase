'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

type WsInfo = { user: { full_name: string; email: string }; workspace: { id: string; name: string; description: string | null } };

export default function Settings() {
  const [info,   setInfo]   = useState<WsInfo | null>(null);
  const [name,   setName]   = useState('');
  const [desc,   setDesc]   = useState('');
  const [saving, setSaving] = useState(false);
  const [saved,  setSaved]  = useState(false);
  const [error,  setError]  = useState('');

  useEffect(() => {
    api('workspace/me').then((d: WsInfo) => {
      setInfo(d);
      setName(d.workspace.name);
      setDesc(d.workspace.description ?? '');
    }).catch(() => {});
  }, []);

  async function save() {
    setSaving(true); setError(''); setSaved(false);
    try {
      await api('workspace/settings', {
        method: 'PATCH',
        body: JSON.stringify({ name: name.trim() || undefined, description: desc.trim() || null }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: any) {
      setError(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: 600 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>Settings</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>Workspace configuration</p>
      </div>

      {/* Workspace info */}
      <div className="ws-card" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 20 }}>
          Workspace
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <label className="ws-label">Workspace name</label>
            <input className="ws-input" value={name} onChange={e => setName(e.target.value)} placeholder="My Workspace" />
          </div>
          <div>
            <label className="ws-label">Description <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>(optional)</span></label>
            <input className="ws-input" value={desc} onChange={e => setDesc(e.target.value)} placeholder="What this workspace is for" />
          </div>

          {error && <div style={{ fontSize: 13, color: 'var(--red)' }}>{error}</div>}
          {saved && <div style={{ fontSize: 13, color: 'var(--accent)' }}>✓ Saved successfully</div>}

          <button className="ws-btn ws-btn-primary ws-btn-sm" onClick={save} disabled={saving || !name.trim()}
            style={{ alignSelf: 'flex-start' }}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>

      {/* Account info (read-only) */}
      <div className="ws-card">
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 20 }}>
          Account
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {[
            { label: 'Name',  value: info?.user.full_name || '—' },
            { label: 'Email', value: info?.user.email     || '—' },
          ].map(({ label, value }) => (
            <div key={label}>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', fontWeight: 500, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 14, color: 'var(--text-sub)' }}>{value}</div>
            </div>
          ))}
          <p style={{ fontSize: 12, color: 'var(--text-dim)', margin: '4px 0 0' }}>
            To change your password, use <a href="/forgot-password" style={{ color: 'var(--accent)', textDecoration: 'none' }}>forgot password</a>.
          </p>
        </div>
      </div>
    </div>
  );
}
