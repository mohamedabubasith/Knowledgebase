'use client';
import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, FileText, RefreshCw, Search, Trash2, Upload } from 'lucide-react';
import { api } from '@/lib/api';

type KB  = { id: string; name: string; description: string | null };
type Doc = { id: string; filename: string; file_size: number; status: string; processing_stage: string; error_message: string | null; created_at: string };
type SearchResult = { document_id: string; filename: string; score: number; text: string };

const TERMINAL = new Set(['completed', 'indexed', 'failed', 'error']);

const STAGE_COLOR: Record<string, string> = {
  completed: '#76b900', indexed: '#76b900',
  embedding: '#a8ff00', chunking: '#f59e0b',
  parsing: '#f59e0b',  queued: '#6b7280',
  failed: '#ef4444',   error: '#ef4444',
};

function fmt(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b/1024).toFixed(1)} KB`;
  return `${(b/1024/1024).toFixed(1)} MB`;
}

export default function KBDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [kb,       setKb]       = useState<KB | null>(null);
  const [docs,     setDocs]     = useState<Doc[]>([]);
  const [tab,      setTab]      = useState<'docs' | 'search' | 'query'>('docs');
  const [uploading, setUploading] = useState(false);
  const [query,    setQuery]    = useState('');
  const [results,  setResults]  = useState<SearchResult[]>([]);
  const [answer,   setAnswer]   = useState('');
  const [searching, setSearching] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadDocs = () => api(`knowledge-bases/${id}/documents`).then(setDocs).catch(() => {});

  useEffect(() => {
    api(`knowledge-bases/${id}`).then(setKb).catch(() => {});
    loadDocs();
  }, [id]);

  // Live poll in-progress docs
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    const pending = docs.filter(d => !TERMINAL.has(d.status) && !TERMINAL.has(d.processing_stage));
    if (!pending.length) return;

    pollRef.current = setInterval(async () => {
      const qs = pending.map(d => `ids=${d.id}`).join('&');
      try {
        const updates: Record<string, { status: string; processing_stage: string; error_message: string | null }> =
          await api(`knowledge-bases/${id}/documents/status?${qs}`);
        setDocs(prev => prev.map(d => {
          const u = updates[d.id];
          return u ? { ...d, ...u } : d;
        }));
        const stillPending = Object.values(updates).some(u => !TERMINAL.has(u.status) && !TERMINAL.has(u.processing_stage));
        if (!stillPending && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      } catch { /* ignore */ }
    }, 3000);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [docs.map(d => d.id).join(','), id]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append('file', file);
      await fetch(`/frontend-api/backend/knowledge-bases/${id}/documents/upload`, {
        method: 'POST', body: form,
      }).catch(() => {});
    }
    setUploading(false);
    loadDocs();
  }

  async function del(docId: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return;
    await api(`knowledge-bases/${id}/documents/${docId}`, { method: 'DELETE' }).catch(() => {});
    loadDocs();
  }

  async function reprocess(docId: string) {
    await api(`knowledge-bases/${id}/documents/${docId}/reprocess`, { method: 'POST' }).catch(() => {});
    loadDocs();
  }

  async function doSearch() {
    if (!query.trim()) return;
    setSearching(true);
    setResults([]); setAnswer('');
    try {
      if (tab === 'search') {
        const r = await api('query/search', { method: 'POST', body: JSON.stringify({ query, knowledge_base_id: id, top_k: 8 }) });
        setResults(r.results ?? []);
      } else {
        const r = await api('query/ask', { method: 'POST', body: JSON.stringify({ query, knowledge_base_id: id }) });
        setAnswer(r.answer ?? '');
        setResults(r.sources ?? []);
      }
    } catch { /* ignore */ } finally {
      setSearching(false);
    }
  }

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Back */}
      <button onClick={() => router.push('/workspace/knowledge-bases')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0, fontFamily: 'var(--font)' }}>
        <ArrowLeft size={14} /> Back to Knowledge Bases
      </button>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>
            {kb?.name ?? '…'}
          </h1>
          {kb?.description && <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>{kb.description}</p>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={loadDocs}>
            <RefreshCw size={13} />
          </button>
          <button className="ws-btn ws-btn-primary ws-btn-sm" disabled={uploading}
            onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> {uploading ? 'Uploading…' : 'Upload'}
          </button>
          <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
            accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx"
            onChange={e => upload(e.target.files)} />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
        {(['docs', 'search', 'query'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{
              padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 500, fontFamily: 'var(--font)',
              color: tab === t ? 'var(--accent)' : 'var(--text-dim)',
              borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent',
              marginBottom: -1, transition: 'color .15s',
            }}>
            {t === 'docs' ? `Documents (${docs.length})` : t === 'search' ? 'Search' : 'Ask AI'}
          </button>
        ))}
      </div>

      {/* ── Documents tab ── */}
      {tab === 'docs' && (
        <div>
          {/* Drop zone */}
          <div
            style={{
              border: '2px dashed var(--border-g)', borderRadius: 12,
              padding: '28px 20px', textAlign: 'center', marginBottom: 16,
              background: 'var(--accent-low)', cursor: 'pointer',
              transition: 'background .15s',
            }}
            onDragOver={e => { e.preventDefault(); (e.currentTarget as HTMLDivElement).style.background = 'rgba(118,185,0,0.1)'; }}
            onDragLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'var(--accent-low)'; }}
            onDrop={e => { e.preventDefault(); (e.currentTarget as HTMLDivElement).style.background = 'var(--accent-low)'; upload(e.dataTransfer.files); }}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={20} style={{ color: 'var(--accent)', display: 'block', margin: '0 auto 8px' }} />
            <div style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>
              Drop files here or click to upload
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              PDF, DOCX, TXT, MD, CSV, XLSX · max 100 MB each
            </div>
          </div>

          {docs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-dim)', fontSize: 13 }}>
              No documents yet. Upload your first file above.
            </div>
          ) : (
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
              <table className="ws-table">
                <thead><tr>
                  <th>File</th><th>Size</th><th>Status</th><th>Uploaded</th><th></th>
                </tr></thead>
                <tbody>
                  {docs.map(doc => {
                    const inProgress = !TERMINAL.has(doc.status) && !TERMINAL.has(doc.processing_stage);
                    const stageColor = STAGE_COLOR[doc.status] ?? STAGE_COLOR[doc.processing_stage] ?? 'var(--text-dim)';
                    return (
                      <tr key={doc.id}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <FileText size={14} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                            <span style={{ fontWeight: 500, color: 'var(--text-sub)' }}>{doc.filename}</span>
                          </div>
                        </td>
                        <td style={{ color: 'var(--text-dim)' }}>{fmt(doc.file_size)}</td>
                        <td>
                          <span style={{
                            display: 'inline-flex', alignItems: 'center', gap: 5,
                            padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600,
                            background: `${stageColor}15`, color: stageColor,
                            border: `1px solid ${stageColor}33`,
                          }}>
                            {inProgress && (
                              <span className="pulse-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: stageColor, display: 'inline-block' }} />
                            )}
                            {doc.processing_stage || doc.status}
                          </span>
                        </td>
                        <td style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                            {(doc.status === 'failed' || doc.status === 'error') && (
                              <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={() => reprocess(doc.id)}
                                title="Reprocess">
                                <RefreshCw size={12} />
                              </button>
                            )}
                            <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={() => del(doc.id, doc.filename)}
                              style={{ padding: '5px 8px' }}>
                              <Trash2 size={12} style={{ color: 'var(--red)' }} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Search / Ask tab ── */}
      {(tab === 'search' || tab === 'query') && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <input className="ws-input" value={query} onChange={e => setQuery(e.target.value)}
              placeholder={tab === 'search' ? 'Search across documents…' : 'Ask a question…'}
              onKeyDown={e => e.key === 'Enter' && doSearch()}
              style={{ flex: 1 }} />
            <button className="ws-btn ws-btn-primary" onClick={doSearch} disabled={searching || !query.trim()}>
              <Search size={14} /> {searching ? 'Searching…' : 'Search'}
            </button>
          </div>

          {/* AI Answer */}
          {answer && (
            <div style={{
              background: 'var(--bg-surface)', border: '1px solid var(--border-g)',
              borderRadius: 12, padding: '20px 22px', marginBottom: 16,
            }}>
              <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', marginBottom: 10 }}>
                AI Answer
              </div>
              <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7, color: 'var(--text-sub)', whiteSpace: 'pre-wrap' }}>{answer}</p>
            </div>
          )}

          {/* Results */}
          {results.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 600, marginBottom: 4 }}>
                {answer ? 'Sources' : `${results.length} result${results.length !== 1 ? 's' : ''}`}
              </div>
              {results.map((r, i) => (
                <div key={i} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <FileText size={13} style={{ color: 'var(--accent)' }} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-sub)' }}>{r.filename}</span>
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'monospace' }}>
                      {(r.score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>{r.text}</p>
                </div>
              ))}
            </div>
          )}

          {!searching && query && results.length === 0 && !answer && (
            <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-dim)', fontSize: 13 }}>
              No results found. Try a different query.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
