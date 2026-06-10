'use client';
import { FormEvent, useEffect, useState } from 'react';
import { BookOpen, Share2, Trash2, Users, X } from 'lucide-react';
import { api } from '@/lib/api';

type KB = { id: string; name: string; description: string | null; is_public: boolean; owner_id: string };
type Share = { id: string; knowledge_base_id: string; granted_to: string; grantee_email: string; grantee_name: string | null; role: 'read' | 'write' | 'delete' };

const ROLES: ('read' | 'write' | 'delete')[] = ['read', 'write', 'delete'];

function RoleChip({ role }: { role: string }) {
  return <span className={`role-chip role-${role}`}>{role}</span>;
}

function ShareModal({ kb, onClose }: { kb: KB; onClose: () => void }) {
  const [shares, setShares] = useState<Share[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'read' | 'write' | 'delete'>('read');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const load = () => api(`knowledge-bases/${kb.id}/shares`).then(setShares).catch(() => {});
  useEffect(() => { load(); }, [kb.id]);

  async function addShare(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSaving(true);
    setErr('');
    try {
      await api(`knowledge-bases/${kb.id}/shares`, {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), role }),
      });
      setEmail('');
      load();
    } catch (ex: any) {
      setErr(ex.message ?? 'Failed to share');
    } finally {
      setSaving(false);
    }
  }

  async function changeRole(userId: string, newRole: string) {
    await api(`knowledge-bases/${kb.id}/shares/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ role: newRole }),
    });
    load();
  }

  async function revoke(userId: string) {
    if (!confirm('Revoke access?')) return;
    await api(`knowledge-bases/${kb.id}/shares/${userId}`, { method: 'DELETE' });
    load();
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: '#a8ff00' }}>
              <Share2 size={14} style={{ display: 'inline', marginRight: 8, verticalAlign: 'middle' }} />
              Share KB
            </div>
            <div style={{ fontSize: 12, color: '#4a6a35', marginTop: 4 }}>{kb.name}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4a6a35', padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        {/* Add share form */}
        <form onSubmit={addShare} style={{ marginBottom: 24 }}>
          <div className="section-label">Add user</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input
              className="input"
              type="email"
              placeholder="user@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              style={{ flex: 1, minWidth: 180 }}
            />
            <select
              className="input"
              value={role}
              onChange={e => setRole(e.target.value as any)}
              style={{ width: 100 }}
            >
              {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <button className="button" type="submit" disabled={saving || !email.trim()}>
              {saving ? '…' : 'Share'}
            </button>
          </div>
          {err && <div style={{ color: '#ff6666', fontSize: 12, marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 10, display: 'flex', gap: 12 }}>
            {[
              { role: 'read', desc: 'Search & query' },
              { role: 'write', desc: 'Upload docs' },
              { role: 'delete', desc: 'Delete docs & KB' },
            ].map(({ role: r, desc }) => (
              <div key={r} style={{ fontSize: 11, color: '#4a6a35' }}>
                <RoleChip role={r} /> <span style={{ marginLeft: 4 }}>{desc}</span>
              </div>
            ))}
          </div>
        </form>

        {/* Current shares */}
        <div className="section-label">Current access ({shares.length})</div>
        {shares.length === 0 ? (
          <div style={{ color: '#3d5a28', fontSize: 13, padding: '12px 0' }}>Not shared with anyone yet.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {shares.map(s => (
              <div key={s.id} style={{
                display: 'flex', gap: 10, alignItems: 'center',
                padding: '10px 12px',
                background: 'rgba(118,185,0,0.03)',
                border: '1px solid rgba(118,185,0,0.08)',
                borderRadius: 8,
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: '#c8dca0', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.grantee_name ?? s.grantee_email}
                  </div>
                  {s.grantee_name && (
                    <div style={{ fontSize: 11, color: '#4a6a35' }}>{s.grantee_email}</div>
                  )}
                </div>
                <select
                  className="input"
                  value={s.role}
                  onChange={e => changeRole(s.granted_to, e.target.value)}
                  style={{ width: 90, padding: '5px 8px', fontSize: 12 }}
                >
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <button
                  className="button button-danger button-sm"
                  onClick={() => revoke(s.granted_to)}
                  title="Revoke"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function KBCard({ kb, onDeleted }: { kb: KB; onDeleted: () => void }) {
  const [showShare, setShowShare] = useState(false);

  async function del() {
    if (!confirm(`Delete "${kb.name}"? This removes all documents and chunks.`)) return;
    try {
      await api(`knowledge-bases/${kb.id}`, { method: 'DELETE' });
      onDeleted();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <>
      <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Header */}
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8, flexShrink: 0,
            background: 'rgba(118,185,0,0.08)',
            border: '1px solid rgba(118,185,0,0.15)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <BookOpen size={16} style={{ color: '#76b900' }} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 800, fontSize: 14, color: '#c8dca0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {kb.name}
            </div>
            <div style={{ fontSize: 12, color: '#4a6a35', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {kb.description || 'No description'}
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          <button
            className="button button-ghost button-sm"
            onClick={() => setShowShare(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 5 }}
          >
            <Users size={12} /> Share
          </button>
          <button
            className="button button-danger button-sm"
            onClick={del}
            style={{ display: 'flex', alignItems: 'center', gap: 5, marginLeft: 'auto' }}
          >
            <Trash2 size={12} /> Delete
          </button>
        </div>
      </div>

      {showShare && <ShareModal kb={kb} onClose={() => setShowShare(false)} />}
    </>
  );
}

export default function KnowledgeBases() {
  const [items, setItems] = useState<KB[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);

  const load = () => api('knowledge-bases').then(setItems).catch(() => {});
  useEffect(() => { load(); }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      await api('knowledge-bases', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setName('');
      setDescription('');
      load();
    } catch (ex: any) {
      alert(ex.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 900, letterSpacing: '-.02em' }}>
          <span style={{ color: '#76b900' }}>◈</span> Knowledge Bases
        </h1>
        <p style={{ color: '#4a6a35', fontSize: 13, margin: '6px 0 0' }}>
          Create isolated retrieval spaces. Share with teammates using role-based access.
        </p>
      </div>

      {/* Create form */}
      <form onSubmit={create} style={{ marginBottom: 28 }}>
        <div className="card" style={{ padding: 18 }}>
          <div className="section-label">Create knowledge base</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <input
              className="input"
              placeholder="Name"
              value={name}
              onChange={e => setName(e.target.value)}
              style={{ minWidth: 200, flex: '0 0 auto' }}
            />
            <input
              className="input"
              placeholder="Description (optional)"
              value={description}
              onChange={e => setDescription(e.target.value)}
              style={{ flex: 1, minWidth: 220 }}
            />
            <button className="button" type="submit" disabled={creating || !name.trim()}>
              {creating ? 'Creating…' : '+ Create'}
            </button>
          </div>
        </div>
      </form>

      {/* KB grid */}
      {items.length === 0 ? (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#3d5a28' }}>
          <BookOpen size={32} style={{ color: '#2a4010', marginBottom: 12 }} />
          <div style={{ fontSize: 14 }}>No knowledge bases yet. Create one above.</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
          {items.map(kb => <KBCard key={kb.id} kb={kb} onDeleted={load} />)}
        </div>
      )}
    </>
  );
}
