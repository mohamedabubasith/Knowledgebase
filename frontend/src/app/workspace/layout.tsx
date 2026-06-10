'use client';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { BookOpen, Code2, LayoutDashboard, LogOut, Settings, Users } from 'lucide-react';
import { api } from '@/lib/api';
import '../workspace.css';

type WorkspaceInfo = {
  user: { id: string; email: string; full_name: string };
  workspace: { id: string; name: string; api_key_prefix: string };
  stats: { knowledge_bases: number; documents: number; chunks: number; prompts_today: number };
};

const NAV = [
  { href: '/workspace',            label: 'Overview',         icon: LayoutDashboard, exact: true },
  { href: '/workspace/knowledge-bases', label: 'Knowledge Bases', icon: BookOpen },
  { href: '/workspace/members',    label: 'Members',          icon: Users },
  { href: '/workspace/developer',  label: 'Developer',        icon: Code2 },
  { href: '/workspace/settings',   label: 'Settings',         icon: Settings },
];

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);

  useEffect(() => {
    api('workspace/me').then(setInfo).catch(() => {});
  }, []);

  async function logout() {
    await fetch('/frontend-api/session/logout', { method: 'POST' });
    router.push('/');
  }

  function isActive(href: string, exact?: boolean) {
    return exact ? pathname === href : pathname.startsWith(href);
  }

  return (
    <div className="ws-body" style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <aside style={{
        width: 220, flexShrink: 0,
        background: 'rgba(10,12,18,0.95)',
        borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column',
        position: 'fixed', top: 0, left: 0, bottom: 0, zIndex: 50,
      }}>
        {/* Logo + workspace name */}
        <div style={{ padding: '20px 16px 12px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: '#fff', letterSpacing: '-.02em', marginBottom: 2 }}>
            Atlas <span style={{ color: 'var(--accent)' }}>KB</span>
          </div>
          <div style={{
            fontSize: 11, fontWeight: 600, color: 'var(--accent)',
            background: 'var(--accent-low)', border: '1px solid var(--border-g)',
            borderRadius: 6, padding: '2px 8px', marginTop: 8,
            display: 'inline-block', letterSpacing: '.04em',
          }}>
            {info?.workspace.name || '…'}
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {NAV.map(({ href, label, icon: Icon, exact }) => (
            <button key={href} onClick={() => router.push(href)}
              className={`ws-nav-link${isActive(href, exact) ? ' active' : ''}`}>
              <Icon size={15} />
              {label}
            </button>
          ))}
        </nav>

        {/* User + logout */}
        <div style={{ padding: '12px 8px', borderTop: '1px solid var(--border)' }}>
          {info && (
            <div style={{ padding: '8px 12px', marginBottom: 6 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-sub)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {info.user.full_name || info.user.email}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {info.user.email}
              </div>
            </div>
          )}
          <button onClick={logout} className="ws-nav-link" style={{ color: 'var(--text-dim)', width: '100%' }}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, marginLeft: 220, padding: '32px 36px', maxWidth: '100%', overflowX: 'hidden' }}>
        {children}
      </main>
    </div>
  );
}
