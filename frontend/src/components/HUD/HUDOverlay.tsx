/**
 * HUDOverlay — full viewport heads-up display.
 *
 * Layout (pointer-events: none on wrapper):
 *  ┌──────────────────────────────────────────────────┐
 *  │ NEXUS GLOBE       ● Connected   ✈ 4,832          │
 *  │ 14:32:07 UTC                                     │
 *  │                                                  │
 *  └──────────────────────────────────────────────────┘
 */
import WorldClock from './WorldClock';
import LiveStats from './LiveStats';
import { useGlobeStore } from '../../stores/globeStore';

const STATUS_COLORS = {
  connected:    '#00ff88',
  connecting:   '#ffee00',
  disconnected: '#ff2244',
} as const;

export default function HUDOverlay() {
  const wsStatus = useGlobeStore((s) => s.wsStatus);
  const dotColor = STATUS_COLORS[wsStatus];

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        padding: '14px 18px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* ── Top bar ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '1rem',
        }}
      >
        {/* ── Left: title + clock ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 900,
              fontSize: 'clamp(0.9rem, 2.2vw, 1.35rem)',
              letterSpacing: '0.3em',
              color: 'var(--neon-cyan)',
              textShadow: 'var(--text-glow)',
              lineHeight: 1,
            }}
          >
            NEXUS GLOBE
          </span>
          <WorldClock />
        </div>

        {/* ── Right: status dot + layer counts ── */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              color: dotColor,
              textShadow: `0 0 6px ${dotColor}`,
            }}
          >
            {/* Connection dot */}
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: dotColor,
                boxShadow: `0 0 6px ${dotColor}`,
                display: 'inline-block',
                animation: wsStatus === 'connected' ? undefined : 'nexus-pulse 1s infinite',
              }}
            />
            {wsStatus === 'connected'
              ? 'Connected'
              : wsStatus === 'connecting'
              ? 'Connecting…'
              : 'Offline'}
          </div>
          <LiveStats />
        </div>
      </div>
    </div>
  );
}

