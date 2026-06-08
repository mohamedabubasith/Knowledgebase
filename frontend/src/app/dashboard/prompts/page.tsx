'use client';
import { useEffect, useState } from 'react';
import PromptTable from '@/components/PromptTable';
import { api } from '@/lib/api';

export default function Prompts() {
  const [items, setItems] = useState<any[]>([]);
  const [status, setStatus] = useState('');
  const [searchType, setSearchType] = useState('');
  const [minScore, setMinScore] = useState('');

  useEffect(() => {
    const q = new URLSearchParams({ page_size: '100' });
    if (status) q.set('status', status);
    if (searchType) q.set('search_type', searchType);
    if (minScore) q.set('min_score', minScore);
    api(`admin/prompt-logs?${q}`).then((x: any) => setItems(x.items ?? [])).catch(() => {});
  }, [status, searchType, minScore]);

  function csv() {
    const rows = [
      ['timestamp', 'prompt', 'response', 'sources', 'latency_ms', 'status', 'search_type'],
      ...items.map(x => [x.created_at, x.prompt, x.response, JSON.stringify(x.sources), x.latency_ms, x.status, x.search_type]),
    ];
    const blob = new Blob([rows.map(r => r.map((v: any) => `"${String(v ?? '').replaceAll('"', '""')}"`).join(',')).join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'prompt-logs.csv';
    a.click();
  }

  return (
    <>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 900, letterSpacing: '-.02em' }}>
          <span style={{ color: '#76b900' }}>◈</span> Prompt Logs
        </h1>
        <p style={{ color: '#5a7040', fontSize: 13, margin: '6px 0 0' }}>Audit every query, response, source, and failure.</p>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <select className="input" value={status} onChange={e => setStatus(e.target.value)} style={{ width: 160 }}>
          <option value="">All statuses</option>
          <option>success</option>
          <option>failed</option>
        </select>
        <select className="input" value={searchType} onChange={e => setSearchType(e.target.value)} style={{ width: 180 }}>
          <option value="">All search types</option>
          <option>hybrid</option>
          <option>dense</option>
          <option>sparse</option>
        </select>
        <input className="input" type="number" min="0" max="1" step=".1" placeholder="Min score"
          value={minScore} onChange={e => setMinScore(e.target.value)} style={{ width: 130 }} />
        <button className="button" onClick={csv}>Export CSV</button>
      </div>

      <div className="card" style={{ overflow: 'auto' }}>
        <PromptTable items={items} />
      </div>
    </>
  );
}
