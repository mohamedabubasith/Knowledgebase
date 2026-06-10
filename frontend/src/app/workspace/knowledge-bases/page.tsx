'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, Plus, Search, Trash2 } from 'lucide-react';
import { api } from '@/lib/api';

type KB = { id: string; name: string; description: string | null; is_public: boolean; created_at: string };

export default function KnowledgeBases() {
  const router = useRouter();
  const [kbs,     setKbs]     = useState<KB[]>([]);
  const [search,  setSearch]  = useState('');
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState('');

  const load = () => api('knowledge-bases').then(setKbs).catch(() => {});
  useEffect(() => { load(); }, []);

  async function create() {
    if (!newName.trim()) return;
    setSaving(true);
    setError('');
    try {
      await api('knowledge-bases', {
        method: 'POST',
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null, is_public: false }),
      });
      setCreating(false);
      setNewName('');
      setNewDesc('');
      load();
    } catch (e: any) {
      setError(e.message || 'Failed to create');
    } finally {
      setSaving(false);
    }
  }

  async function del(id: string, name: string) {
    if (!confirm(`Delete "${name}"?\nThis permanently removes all documents and vectors.`)) return;
    await api(`knowledge-bases/${id}`, { method: 'DELETE' }).catch(() => {});
    load();
  }

  const filtered = kbs.filter(kb => kb.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div style={{ maxWidth: 860 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>Knowledge Bases</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>
            {kbs.length} workspace{kbs.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button className="ws-btn ws-btn-primary" onClick={() => setCreating(true)}>
          <Plus size={15} /> New KB
        </button>
      </div>

      {/* Create modal */}
      {creating && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        }}>
          <div className="ws-card" style={{ width: '100%', maxWidth: 420, padding: '28px 28px' }}>
            <h3 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 700, color: '#fff' }}>New Knowledge Base</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label className="ws-label">Name</label>
                <input className="ws-input" value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="Product docs, Support KB…" autoFocus />
              </div>
              <div>
                <label className="ws-label">Description <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>(optional)</span></label>
                <input className="ws-input" value={newDesc} onChange={e => setNewDesc(e.target.value)}
                  placeholder="What's this KB about?" />
              </div>
              {error && <div style={{ fontSize: 13, color: 'var(--red)' }}>{error}</div>}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
                <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={() => { setCreating(false); setError(''); }}>Cancel</button>
                <button className="ws-btn ws-btn-primary ws-btn-sm" onClick={create} disabled={saving || !newName.trim()}>
                  {saving ? 'Creating…' : 'Create'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Search */}
      {kbs.length > 3 && (
        <div style={{ position: 'relative', marginBottom: 16 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }} />
          <input className="ws-input" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search knowledge bases…" style={{ paddingLeft: 36 }} />
        </div>
      )}

      {/* List */}
      {filtered.length === 0 ? (
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12,
          padding: '56px 24px', textAlign: 'center',
        }}>
          <BookOpen size={28} style={{ color: 'var(--text-dim)', opacity: .4, display: 'block', margin: '0 auto 12px' }} />
          <div style={{ fontSize: 14, color: 'var(--text-dim)' }}>
            {search ? 'No results found.' : 'No knowledge bases yet.'}
          </div>
          {!search && (
            <button className="ws-btn ws-btn-primary ws-btn-sm" onClick={() => setCreating(true)} style={{ marginTop: 16 }}>
              <Plus size={13} /> Create first KB
            </button>
          )}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.map(kb => (
            <div key={kb.id}
              style={{
                background: 'var(--bg-surface)', border: '1px solid var(--border)',
                borderRadius: 12, padding: '16px 20px',
                display: 'flex', alignItems: 'center', gap: 16,
                transition: 'border-color .15s, box-shadow .15s', cursor: 'pointer',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-g)';
                (e.currentTarget as HTMLDivElement).style.boxShadow = '0 0 16px var(--accent-dim)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
                (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
              }}
              onClick={() => router.push(`/workspace/knowledge-bases/${kb.id}`)}
            >
              <div style={{
                width: 40, height: 40, borderRadius: 10, flexShrink: 0,
                background: 'var(--accent-low)', border: '1px solid var(--border-g)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <BookOpen size={18} style={{ color: 'var(--accent)' }} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 2 }}>{kb.name}</div>
                {kb.description && (
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {kb.description}
                  </div>
                )}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                {new Date(kb.created_at).toLocaleDateString()}
              </div>
              <button className="ws-btn ws-btn-ghost ws-btn-sm"
                onClick={e => { e.stopPropagation(); del(kb.id, kb.name); }}
                style={{ flexShrink: 0, padding: '6px 10px' }}>
                <Trash2 size={13} style={{ color: 'var(--red)' }} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
