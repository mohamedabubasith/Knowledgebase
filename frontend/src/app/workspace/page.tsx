'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, FileText, MessageSquare, Zap } from 'lucide-react';
import { api } from '@/lib/api';

type Info = {
  user: { full_name: string; email: string };
  workspace: { name: string; api_key_prefix: string };
  stats: { knowledge_bases: number; documents: number; chunks: number; prompts_today: number };
};

export default function WorkspaceOverview() {
  const router = useRouter();
  const [info, setInfo] = useState<Info | null>(null);

  useEffect(() => {
    api('workspace/me').then(setInfo).catch(() => {});
  }, []);

  const stats = [
    { label: 'Knowledge Bases', value: info?.stats.knowledge_bases ?? '—', icon: BookOpen,     href: '/workspace/knowledge-bases', accent: 'var(--accent)' },
    { label: 'Documents',       value: info?.stats.documents       ?? '—', icon: FileText,     href: '/workspace/knowledge-bases', accent: 'var(--accent)' },
    { label: 'Chunks Indexed',  value: info?.stats.chunks?.toLocaleString() ?? '—', icon: Zap,  href: '/workspace/knowledge-bases', accent: '#a8ff00' },
    { label: 'Prompts Today',   value: info?.stats.prompts_today   ?? '—', icon: MessageSquare, href: '/workspace/knowledge-bases', accent: '#f59e0b' },
  ];

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: '#fff', letterSpacing: '-.02em' }}>
          {info ? `Welcome back, ${info.user.full_name || info.user.email.split('@')[0]}` : 'Welcome back'}
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--text-dim)' }}>
          {info?.workspace.name} workspace overview
        </p>
      </div>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 32 }}>
        {stats.map(({ label, value, icon: Icon, href, accent }) => (
          <div key={label} onClick={() => router.push(href)}
            style={{
              background: 'var(--bg-surface)', border: '1px solid var(--border)',
              borderRadius: 12, padding: '20px 20px', cursor: 'pointer',
              transition: 'border-color .15s, box-shadow .15s',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-g)';
              (e.currentTarget as HTMLDivElement).style.boxShadow = '0 0 20px var(--accent-dim)';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
              (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
            }}>
            <Icon size={18} style={{ color: accent, marginBottom: 10 }} />
            <div style={{ fontSize: 28, fontWeight: 800, color: accent, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 5, fontWeight: 500 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 600, marginBottom: 14 }}>
          Quick actions
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            { label: '+ New knowledge base', href: '/workspace/knowledge-bases' },
            { label: 'Invite a member',       href: '/workspace/members' },
            { label: 'Get API key',           href: '/workspace/developer' },
          ].map(({ label, href }) => (
            <button key={href} onClick={() => router.push(href)}
              className="ws-btn ws-btn-ghost ws-btn-sm"
              style={{ fontSize: 13 }}>
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
