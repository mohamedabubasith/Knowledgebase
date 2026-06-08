'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, Gauge, Key } from 'lucide-react';

const links = [
  ['/dashboard', Gauge, 'Overview'],
  ['/dashboard/tenants', Key, 'Tenants'],
  ['/dashboard/worker', Activity, 'Worker'],
] as const;

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside style={{
      width: 220,
      position: 'fixed', top: 0, left: 0, bottom: 0,
      zIndex: 100,
      display: 'flex', flexDirection: 'column',
      background: 'rgba(0,0,0,0.78)',
      backdropFilter: 'blur(22px)',
      WebkitBackdropFilter: 'blur(22px)',
      borderRight: '1px solid rgba(118,185,0,0.09)',
      padding: '22px 12px',
    }}>
      {/* Logo */}
      <div style={{ padding: '2px 10px 28px' }}>
        <div style={{
          fontSize: 15, fontWeight: 900, letterSpacing: '.18em',
          color: '#76b900', textTransform: 'uppercase', fontFamily: 'monospace',
          textShadow: '0 0 16px rgba(118,185,0,0.45)',
        }}>
          ◈ CORTEX
        </div>
        <div style={{
          fontSize: 11, fontWeight: 900, letterSpacing: '.24em',
          color: '#a8ff00', textTransform: 'uppercase', fontFamily: 'monospace',
          marginTop: 1,
          textShadow: '0 0 10px rgba(168,255,0,0.3)',
        }}>
          KB
        </div>
        <div style={{ fontSize: 9, color: '#2d4a1e', letterSpacing: '.15em', marginTop: 5, fontFamily: 'monospace' }}>
          ADMIN CONSOLE
        </div>
        <div style={{
          height: 1, marginTop: 12,
          background: 'linear-gradient(90deg, rgba(118,185,0,0.5), transparent)',
        }} />
      </div>

      {/* Nav */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
        {links.map(([href, Icon, label]) => {
          const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href));
          return (
            <Link key={href} href={href} style={{
              display: 'flex', gap: 10, padding: '10px 12px',
              color: active ? '#a8ff00' : '#3d5a28',
              textDecoration: 'none', borderRadius: 9,
              background: active ? 'rgba(118,185,0,0.1)' : 'transparent',
              border: `1px solid ${active ? 'rgba(118,185,0,0.2)' : 'transparent'}`,
              fontSize: 13, fontWeight: active ? 700 : 400,
              transition: 'all .18s', alignItems: 'center',
              boxShadow: active ? '0 0 14px rgba(118,185,0,0.07)' : 'none',
            }}>
              <Icon size={14} style={{ flexShrink: 0 }} />
              <span>{label}</span>
              {active && (
                <span style={{
                  marginLeft: 'auto', width: 5, height: 5, borderRadius: '50%',
                  background: '#76b900', boxShadow: '0 0 8px #76b900',
                }} />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div style={{ padding: '16px 10px 0', borderTop: '1px solid rgba(118,185,0,0.07)' }}>
        <div style={{ fontSize: 9, color: '#1e3010', fontFamily: 'monospace', letterSpacing: '.12em' }}>
          CORTEX-KB · LOCAL AI
        </div>
        <div style={{ fontSize: 9, color: '#162208', marginTop: 2, fontFamily: 'monospace' }}>
          v1.0.0 · PRIVATE
        </div>
      </div>
    </aside>
  );
}
