/**
 * HeatmapToggle — single button to enable/disable heatmap density mode.
 *
 * Story 3.12: Replaces individual markers with a hexagonal H3 density overlay.
 * Keyboard shortcut: H
 */
import { useEffect } from 'react';
import { useGlobeStore } from '../../stores/globeStore';

export default function HeatmapToggle() {
  const heatmapMode    = useGlobeStore((s) => s.heatmapMode);
  const toggleHeatmap  = useGlobeStore((s) => s.toggleHeatmapMode);

  // Keyboard shortcut H
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return;
      if (e.key === 'h' || e.key === 'H') {
        e.preventDefault();
        toggleHeatmap();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleHeatmap]);

  return (
    <button
      onClick={toggleHeatmap}
      title="Toggle heatmap density mode (H)"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        width: '100%',
        background: heatmapMode ? 'rgba(255,238,0,0.12)' : 'rgba(255,255,255,0.03)',
        border: `1px solid ${heatmapMode ? 'rgba(255,238,0,0.6)' : 'rgba(255,255,255,0.08)'}`,
        borderRadius: 3,
        color: heatmapMode ? '#ffee00' : 'rgba(255,238,0,0.45)',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.6rem',
        letterSpacing: '0.12em',
        padding: '5px 10px',
        cursor: 'pointer',
        textShadow: heatmapMode ? '0 0 8px #ffee00' : 'none',
        transition: 'all 0.15s',
      }}
    >
      <span style={{ fontSize: '0.75rem' }}>⬡</span>
      HEATMAP{heatmapMode ? ' ON' : ' OFF'}
      <span
        style={{
          marginLeft: 'auto',
          fontSize: '0.5rem',
          color: 'rgba(255,238,0,0.35)',
        }}
      >
        H
      </span>
    </button>
  );
}
