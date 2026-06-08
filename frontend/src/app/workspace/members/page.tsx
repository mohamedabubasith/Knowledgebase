'use client';
import { useEffect, useState } from 'react';
import { Mail, Plus, UserCheck, Users } from 'lucide-react';
import { api } from '@/lib/api';

type Member = { id: string; email: string; full_name: string | null; role: string; kb_name: string };
type KB     = { id: string; name: string };

export default function Members() {
  const [members, setMembers] = useState<Member[]>([]);
  const [kbs,     setKbs]     = useState<KB[]>([]);
  const [showing, setShowing] = useState(false);
  const [email,   setEmail]   = useState('');
  const [kbId,    setKbId]    = useState('');
  const [role,    setRole]    = useState('read');
  const [saving,  setSaving]  = useState(false);
  const [done,    setDone]    = useState('');
  const [error,   setError]   = useState('');

  const load = () => api('workspace/members').then(setMembers).catch(() => {});
  useEffect(() => {
    load();
    api('knowledge-bases').then(setKbs).catch(() => {});
  }, []);

  async function invite() {
    if (!email.trim() || !kbId) return;
    setSaving(true); setError(''); setDone('');
    try {
      const res = await api('workspace/invite', {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), kb_id: kbId, role }),
      });
      setDone(res.status === 'invited' ? `Invite sent to ${email}` : `${email} added to workspace`);
      setEmail(''); setShowing(false);
      load();
    } catch (e: any) {
      setError(e.message || 'Failed to invite');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>Members</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>Manage workspace access</p>
        </div>
        <button className="ws-btn ws-btn-primary" onClick={() => setShowing(true)}>
          <Plus size={14} /> Invite member
        </button>
      </div>

      {/* Invite modal */}
      {showing && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div className="ws-card" style={{ width: '100%', maxWidth: 420, padding: '28px 28px' }}>
            <h3 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 700, color: '#fff' }}>Invite member</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label className="ws-label">Email address</label>
                <input className="ws-input" type="email" value={email} onChange={e => setEmail(e.target.value)}
                  placeholder="colleague@company.com" autoFocus />
              </div>
              <div>
                <label className="ws-label">Knowledge base</label>
                <select className="ws-input" value={kbId} onChange={e => setKbId(e.target.value)}>
                  <option value="">Select a KB…</option>
                  {kbs.map(kb => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
                </select>
              </div>
              <div>
                <label className="ws-label">Role</label>
                <select className="ws-input" value={role} onChange={e => setRole(e.target.value)}>
                  <option value="read">Read — search & query only</option>
                  <option value="write">Write — can upload documents</option>
                </select>
              </div>
              {error && <div style={{ fontSize: 13, color: 'var(--red)' }}>{error}</div>}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
                <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={() => { setShowing(false); setError(''); }}>Cancel</button>
                <button className="ws-btn ws-btn-primary ws-btn-sm" onClick={invite} disabled={saving || !email.trim() || !kbId}>
                  {saving ? 'Sending…' : 'Send invite'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {done && (
        <div style={{ padding: '12px 16px', background: 'var(--accent-low)', border: '1px solid var(--border-g)', borderRadius: 10, fontSize: 13, color: 'var(--accent)', marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
          <UserCheck size={15} /> {done}
        </div>
      )}

      {members.length === 0 ? (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '56px 24px', textAlign: 'center' }}>
          <Users size={28} style={{ color: 'var(--text-dim)', opacity: .4, display: 'block', margin: '0 auto 12px' }} />
          <div style={{ fontSize: 14, color: 'var(--text-dim)' }}>No shared members yet.</div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>Invite someone to give them access to a knowledge base.</div>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <table className="ws-table">
            <thead><tr><th>User</th><th>Email</th><th>Knowledge Base</th><th>Role</th></tr></thead>
            <tbody>
              {members.map(m => (
                <tr key={`${m.id}-${m.kb_name}`}>
                  <td style={{ fontWeight: 600, color: '#fff' }}>{m.full_name || '—'}</td>
                  <td style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <Mail size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                    {m.email}
                  </td>
                  <td>{m.kb_name}</td>
                  <td>
                    <span className={`ws-badge ${m.role === 'write' ? 'ws-badge-amber' : 'ws-badge-gray'}`}>
                      {m.role}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
