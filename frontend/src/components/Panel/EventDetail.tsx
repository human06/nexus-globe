/**
 * EventDetail — shows metadata for the currently selected event.
 * Designed for flight events (Epic 1), handles others gracefully.
 */
import { formatCoords, formatSpeed, formatTime } from '../../utils/formatters';
import type { GlobeEvent } from '../../types/events';

const TYPE_COLORS: Record<string, string> = {
  flight:    '#ffee00',
  news:      '#00f0ff',
  ship:      '#00ff88',
  satellite: '#ff00aa',
  disaster:  '#ff6600',
  conflict:  '#ff0044',
  traffic:   '#aa44ff',
  camera:    '#888888',
};

const TYPE_LABELS: Record<string, string> = {
  flight:    'FLIGHT',
  news:      'NEWS',
  ship:      'VESSEL',
  satellite: 'SAT',
  disaster:  'DISASTER',
  conflict:  'CONFLICT',
  traffic:   'TRAFFIC',
  camera:    'CAMERA',
};

interface RowProps { label: string; value: string; dim?: boolean }
function Row({ label, value, dim }: RowProps) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: '0.78rem', lineHeight: '1.7', opacity: dim ? 0.55 : 1 }}>
      <span style={{ color: 'rgba(0, 240, 255, 0.4)', minWidth: 80, flexShrink: 0, fontFamily: 'var(--font-mono)' }}>
        {label}
      </span>
      <span style={{ color: '#e0f4ff', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>
        {value}
      </span>
    </div>
  );
}

export default function EventDetail({ event }: { event: GlobeEvent }) {
  const meta  = event.metadata as Record<string, unknown>;
  const color = TYPE_COLORS[event.type] ?? '#fff';
  const label = TYPE_LABELS[event.type] ?? event.type.toUpperCase();

  const ktSpeed = event.speed != null ? (event.speed * 0.539957).toFixed(0) + ' kts' : '—';
  const altFt   = event.altitude != null ? (event.altitude * 3.28084).toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' ft' : '—';
  const heading = event.heading != null ? `${Math.round(event.heading)}°` : '—';

  return (
    <div style={{ padding: '0 2px' }}>
      {/* Type badge + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: '0.6rem',
            letterSpacing: '0.15em',
            color,
            background: `${color}18`,
            border: `1px solid ${color}55`,
            borderRadius: 2,
            padding: '2px 6px',
          }}
        >
          {label}
        </span>
      </div>

      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: '0.92rem',
          fontWeight: 700,
          color,
          textShadow: `0 0 8px ${color}`,
          marginBottom: 10,
          letterSpacing: '0.06em',
          lineHeight: 1.2,
        }}
      >
        {event.title}
      </div>

      {/* Flight-specific fields */}
      {event.type === 'flight' && (
        <div style={{ marginBottom: 8, borderBottom: '1px solid rgba(0,240,255,0.08)', paddingBottom: 8 }}>
          {/* Route banner — show only when we have origin or destination */}
          {(meta?.origin || meta?.destination) && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              margin: '6px 0 10px',
              padding: '5px 10px',
              background: 'rgba(0,240,255,0.06)',
              border: '1px solid rgba(0,240,255,0.18)',
              borderRadius: 3,
              fontFamily: 'var(--font-display)',
              fontSize: '0.9rem',
              letterSpacing: '0.15em',
            }}>
              <span style={{ color: '#e0f4ff', opacity: 0.7 }}>{String(meta.origin || '···')}</span>
              <svg width="20" height="10" viewBox="0 0 20 10" fill="none" stroke="var(--neon-cyan)" strokeWidth="1.5">
                <line x1="0" y1="5" x2="16" y2="5" />
                <polyline points="11,1 17,5 11,9" />
              </svg>
              <span style={{ color: '#e0f4ff', opacity: 0.7 }}>{String(meta.destination || '···')}</span>
            </div>
          )}
          <Row label="FLIGHT"   value={String(meta?.number || meta?.callsign || event.title).trim() || '—'} />
          <Row label="CALLSIGN" value={String(meta?.callsign ?? '—').trim() || '—'} />
          <Row label="AIRCRAFT" value={String(meta?.aircraft || '—').trim()} />
          <Row label="REG"      value={String(meta?.registration || '—').trim()} />
          <Row label="ICAO24"   value={String(meta?.icao24 ?? '—').toUpperCase()} />
        </div>
      )}

      {/* Common fields */}
      <Row label="ALTITUDE"  value={altFt} />
      <Row label="SPEED"     value={`${formatSpeed(event.speed ?? 0)} · ${ktSpeed}`} />
      <Row label="HEADING"   value={heading} />
      <Row label="POSITION"  value={formatCoords(event.latitude, event.longitude)} />
      <Row label="TIME"      value={formatTime(event.timestamp)} />
      <Row label="SEVERITY"  value={String(event.severity)} />
      <Row label="SOURCE"    value={event.source} dim />
    </div>
  );
}

