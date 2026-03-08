import { useMemo } from 'react';
import { useGlobeStore } from '../../stores/globeStore';

const PRESETS: Array<{ label: string; range: [number, number] }> = [
  { label: 'All', range: [1, 5] },
  { label: 'Important (3+)', range: [3, 5] },
  { label: 'Critical (5)', range: [5, 5] },
];

export default function SeveritySlider() {
  const events = useGlobeStore((s) => s.events);
  const severityRange = useGlobeStore((s) => s.severityRange);
  const setSeverityRange = useGlobeStore((s) => s.setSeverityRange);

  const [min, max] = severityRange;

  const { totalEvents, visibleEvents } = useMemo(() => {
    let total = 0;
    let visible = 0;
    for (const ev of events.values()) {
      total += 1;
      if (ev.severity >= min && ev.severity <= max) {
        visible += 1;
      }
    }
    return { totalEvents: total, visibleEvents: visible };
  }, [events, min, max]);

  const setMin = (value: number) => {
    const nextMin = Math.min(value, max);
    setSeverityRange([nextMin, max]);
  };

  const setMax = (value: number) => {
    const nextMax = Math.max(value, min);
    setSeverityRange([min, nextMax]);
  };

  const severityColor = (level: number): string => {
    if (level <= 1) return '#9ca3af';
    if (level === 2) return '#00ff88';
    if (level === 3) return '#ffee00';
    if (level === 4) return '#ff9900';
    return '#ff2244';
  };

  return (
    <div
      style={{
        borderTop: '1px solid rgba(0, 240, 255, 0.12)',
        marginTop: 4,
        padding: '8px 10px 4px',
        display: 'grid',
        gap: 8,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.6rem',
          letterSpacing: '0.08em',
        }}
      >
        <span style={{ color: 'rgba(0, 240, 255, 0.55)' }}>SEVERITY</span>
        <span style={{ color: '#00f0ff' }}>
          {min}–{max}
        </span>
      </div>

      <div style={{ display: 'grid', gap: 4 }}>
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={min}
          onChange={(e) => setMin(Number(e.target.value))}
          aria-label="Minimum severity"
          style={{ accentColor: '#00f0ff' }}
        />
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={max}
          onChange={(e) => setMax(Number(e.target.value))}
          aria-label="Maximum severity"
          style={{ accentColor: '#ff2244' }}
        />
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.52rem',
          letterSpacing: '0.05em',
        }}
      >
        {[1, 2, 3, 4, 5].map((level) => (
          <span key={level} style={{ color: severityColor(level) }}>
            {level}
          </span>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {PRESETS.map((preset) => {
          const active = min === preset.range[0] && max === preset.range[1];
          return (
            <button
              key={preset.label}
              type="button"
              onClick={() => setSeverityRange(preset.range)}
              style={{
                border: active
                  ? '1px solid rgba(0,240,255,0.7)'
                  : '1px solid rgba(255,255,255,0.12)',
                color: active ? '#00f0ff' : 'rgba(255,255,255,0.65)',
                background: 'rgba(0, 0, 0, 0.25)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.5rem',
                letterSpacing: '0.04em',
                padding: '2px 5px',
                borderRadius: 2,
                cursor: 'pointer',
              }}
            >
              {preset.label}
            </button>
          );
        })}
      </div>

      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.52rem',
          color: 'rgba(0, 240, 255, 0.45)',
          letterSpacing: '0.05em',
        }}
      >
        SHOWING {visibleEvents.toLocaleString()} OF {totalEvents.toLocaleString()} EVENTS
      </div>
    </div>
  );
}
