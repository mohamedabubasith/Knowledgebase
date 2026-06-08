export default function StatsCard({
  label, value, accent = '#76b900', sub,
}: { label: string; value: number | string; accent?: string; sub?: string }) {
  return (
    <div className="card" style={{ padding: '18px 20px' }}>
      <div style={{ fontSize: 11, color: '#5a7040', textTransform: 'uppercase', letterSpacing: '.1em', fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 900, color: accent, marginTop: 8, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#3d6000', marginTop: 6 }}>{sub}</div>}
    </div>
  );
}
