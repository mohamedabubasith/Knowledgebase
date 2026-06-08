'use client';
import { useState } from 'react';

function scoreColor(score: number) {
  return score > 0.7 ? '#76b900' : score >= 0.4 ? '#f7c75f' : '#ff6b7a';
}

export default function PromptTable({ items = [] }: { items: any[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (items.length === 0) {
    return <div style={{ padding: 24, textAlign: 'center', color: '#3d6000' }}>No prompt logs yet.</div>;
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Prompt</th>
          <th>Search</th>
          <th>Status</th>
          <th>Latency</th>
          <th>Model</th>
        </tr>
      </thead>
      <tbody>
        {items.map(x => (
          <>
            <tr key={x.id} onClick={() => setExpanded(expanded === x.id ? null : x.id)} style={{ cursor: 'pointer' }}>
              <td style={{ color: '#3d6000', fontSize: 12, whiteSpace: 'nowrap' }}>{new Date(x.created_at).toLocaleString()}</td>
              <td style={{ maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={x.prompt}>
                {x.prompt?.slice(0, 72)}
              </td>
              <td><span className="badge">{x.search_type}</span></td>
              <td>
                <span className={`badge ${x.status === 'success' ? 'badge-green' : 'badge-red'}`}>
                  {x.status}
                </span>
              </td>
              <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#76b900' }}>{x.latency_ms} ms</td>
              <td style={{ color: '#5a7040', fontSize: 12 }}>{x.model_used ?? '—'}</td>
            </tr>
            {expanded === x.id && (
              <tr key={`${x.id}-d`}>
                <td colSpan={6} style={{ padding: '0 14px 14px' }}>
                  <div style={{ display: 'grid', gap: 12, padding: '12px 0' }}>
                    <div>
                      <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 6 }}>Prompt</div>
                      <div style={{ color: '#d0e0b0', fontSize: 13, lineHeight: 1.6 }}>{x.prompt}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: '#3d6000', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700, marginBottom: 6 }}>Response</div>
                      <div style={{ color: '#d0e0b0', fontSize: 13, lineHeight: 1.6 }}>{x.response || x.error}</div>
                    </div>
                    {(x.sources ?? []).map((src: any, i: number) => (
                      <div key={src.chunk_id ?? i} className="card" style={{ padding: 14 }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
                          <a href={src.presigned_url} target="_blank" rel="noreferrer"
                            style={{ color: '#76b900', fontWeight: 700, fontSize: 13 }}>
                            {src.document_name ?? 'Source document'}
                          </a>
                          <span className="badge badge-green" style={{ color: scoreColor(src.similarity_score) }}>
                            {(src.similarity_score * 100).toFixed(0)}%
                          </span>
                          {src.page_number && <span className="badge">p.{src.page_number}</span>}
                        </div>
                        <div style={{ fontSize: 13, color: '#5a7040', lineHeight: 1.5, marginBottom: 8 }}>{src.content}</div>
                        <div style={{ height: 4, background: '#0e0e0e', borderRadius: 99, border: '1px solid #1a280a' }}>
                          <div style={{
                            height: '100%', width: `${Math.min(100, (src.relevance_score ?? 0) * 100)}%`,
                            background: '#76b900', borderRadius: 99,
                          }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </td>
              </tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  );
}
