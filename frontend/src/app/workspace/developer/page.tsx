'use client';
import { useEffect, useState } from 'react';
import { Check, Copy, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';

type WsInfo = { workspace: { api_key_prefix: string; name: string } };

const ENDPOINTS = [
  { method: 'GET',  path: '/api/v1/knowledge-bases',                       desc: 'List all knowledge bases' },
  { method: 'POST', path: '/api/v1/knowledge-bases',                       desc: 'Create a knowledge base' },
  { method: 'GET',  path: '/api/v1/knowledge-bases/{kb_id}/documents',     desc: 'List documents in KB' },
  { method: 'POST', path: '/api/v1/knowledge-bases/{kb_id}/documents/upload', desc: 'Upload a document' },
  { method: 'GET',  path: '/api/v1/knowledge-bases/{kb_id}/documents/status', desc: 'Batch processing status' },
  { method: 'POST', path: '/api/v1/query/search',                          desc: 'Semantic search' },
  { method: 'POST', path: '/api/v1/query/ask',                             desc: 'RAG query (search + LLM)' },
];

const METHOD_COLOR: Record<string, string> = {
  GET: '#76b900', POST: '#f59e0b', DELETE: '#ef4444', PATCH: '#a855f7',
};

export default function Developer() {
  const [info,     setInfo]     = useState<WsInfo | null>(null);
  const [newKey,   setNewKey]   = useState<string | null>(null);
  const [copied,   setCopied]   = useState(false);
  const [rotating, setRotating] = useState(false);

  useEffect(() => { api('workspace/me').then(setInfo).catch(() => {}); }, []);

  async function rotate() {
    if (!confirm('Rotate API key? The current key stops working immediately.')) return;
    setRotating(true);
    try {
      const res = await api('workspace/api-key/rotate', { method: 'POST' });
      setNewKey(res.api_key);
      api('workspace/me').then(setInfo).catch(() => {});
    } finally {
      setRotating(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>Developer</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>API access and endpoint reference</p>
      </div>

      {/* API Key */}
      <div className="ws-card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 16 }}>
          API Key
        </div>

        {newKey ? (
          <div>
            <div style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600, marginBottom: 8 }}>
              ✓ New key generated — copy it now, shown only once
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <code style={{
                flex: 1, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
                borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#b8d890',
                fontFamily: 'monospace', wordBreak: 'break-all',
              }}>
                {newKey}
              </code>
              <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={() => copy(newKey)}>
                {copied ? <Check size={13} style={{ color: 'var(--accent)' }} /> : <Copy size={13} />}
              </button>
            </div>
            <button onClick={() => setNewKey(null)}
              style={{ marginTop: 10, background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--text-dim)', fontFamily: 'var(--font)' }}>
              Dismiss
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>Current key prefix</div>
              <code style={{ fontSize: 13, color: 'var(--text-sub)', fontFamily: 'monospace' }}>
                {info?.workspace.api_key_prefix ?? '…'}···
              </code>
            </div>
            <button className="ws-btn ws-btn-ghost ws-btn-sm" onClick={rotate} disabled={rotating}
              style={{ marginLeft: 'auto' }}>
              <RefreshCw size={13} /> {rotating ? 'Rotating…' : 'Rotate key'}
            </button>
          </div>
        )}
      </div>

      {/* Auth usage */}
      <div className="ws-card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 14 }}>
          Authentication
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 12px', lineHeight: 1.6 }}>
          Pass your API key as a Bearer token in the <code style={{ color: 'var(--accent)', fontFamily: 'monospace' }}>Authorization</code> header:
        </p>
        <pre style={{
          background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#b8d890',
          fontFamily: 'monospace', overflowX: 'auto', margin: 0,
        }}>
{`curl https://your-domain/api/v1/knowledge-bases \\
  -H "Authorization: Bearer ${info?.workspace.api_key_prefix ?? 'YOUR_API_KEY'}···"`}
        </pre>
      </div>

      {/* Endpoint reference */}
      <div className="ws-card">
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 14 }}>
          Endpoint Reference
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, overflow: 'hidden', borderRadius: 8, border: '1px solid var(--border)' }}>
          {ENDPOINTS.map(({ method, path, desc }) => (
            <div key={path} style={{
              display: 'flex', alignItems: 'center', gap: 14,
              padding: '11px 16px', borderBottom: '1px solid rgba(255,255,255,0.03)',
              background: 'rgba(255,255,255,0.01)',
            }}>
              <span style={{
                fontSize: 10, fontWeight: 800, fontFamily: 'monospace',
                color: METHOD_COLOR[method] ?? '#fff',
                background: `${METHOD_COLOR[method]}15`,
                padding: '2px 8px', borderRadius: 4, minWidth: 48, textAlign: 'center',
              }}>
                {method}
              </span>
              <code style={{ fontSize: 12, color: 'var(--text-sub)', fontFamily: 'monospace', flex: 1 }}>{path}</code>
              <span style={{ fontSize: 12, color: 'var(--text-dim)', flexShrink: 0 }}>{desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
