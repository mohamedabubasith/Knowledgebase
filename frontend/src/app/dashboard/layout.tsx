import ParticleBackground from '@/components/ParticleBackground';
import Sidebar from '@/components/Sidebar';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ParticleBackground />
      <Sidebar />
      <main style={{
        marginLeft: 220,
        padding: '32px 36px',
        minHeight: '100vh',
        position: 'relative',
        zIndex: 1,
      }}>
        {children}
      </main>
    </>
  );
}
