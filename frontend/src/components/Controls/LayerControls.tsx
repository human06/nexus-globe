/**
 * LayerControls — vertical stack of layer toggles on the left edge.
 *
 * Story 2.14:
 * - 4 functional layers: ✈ Flights, 📰 News, 🌋 Disasters, 🚢 Ships
 * - 4 "coming soon" layers dimmed (no interactivity)
 * - Keyboard shortcuts 1–4 for the active layers
 * - Footer: "INTEL FEEDS: N/8 ACTIVE"
 */
import { useEffect } from 'react';
import LayerToggle from './LayerToggle';
import { useGlobeStore } from '../../stores/globeStore';

const LAYER_CONFIG = [
  { key: 'flights',    label: '✈ Flights',    color: '#ffee00', type: 'flight',    functional: true,  shortcut: '1' },
  { key: 'news',       label: '📰 News',       color: '#00f0ff', type: 'news',      functional: true,  shortcut: '2' },
  { key: 'disasters',  label: '🌋 Disasters',  color: '#ff6600', type: 'disaster',  functional: true,  shortcut: '3' },
  { key: 'ships',      label: '🚢 Ships',      color: '#00ff88', type: 'ship',      functional: true,  shortcut: '4' },
  { key: 'satellites', label: '🛰 Satellites', color: '#ff00aa', type: 'satellite', functional: false, shortcut: null },
  { key: 'conflicts',  label: '⚔ Conflicts',  color: '#ff0044', type: 'conflict',  functional: false, shortcut: null },
  { key: 'traffic',    label: '🚦 Traffic',    color: '#aa44ff', type: 'traffic',   functional: false, shortcut: null },
  { key: 'cameras',    label: '📷 Cameras',    color: '#888888', type: 'camera',    functional: false, shortcut: null },
] as const;

type LayerKey = (typeof LAYER_CONFIG)[number]['key'];

export default function LayerControls() {
  const layers      = useGlobeStore((s) => s.layers);
  const events      = useGlobeStore((s) => s.events);
  const toggleLayer = useGlobeStore((s) => s.toggleLayer);

  // Count per event type
  const counts: Record<string, number> = {};
  for (const ev of events.values()) {
    counts[ev.type] = (counts[ev.type] ?? 0) + 1;
  }

  // Active count (functional layers with data or toggled on)
  const activeCount = LAYER_CONFIG.filter(
    (l) => l.functional && layers[l.key as LayerKey],
  ).length;

  // Keyboard shortcuts 1–4
  useEffect(() => {
    const keyMap: Record<string, LayerKey> = {
      '1': 'flights',
      '2': 'news',
      '3': 'disasters',
      '4': 'ships',
    };
    const onKey = (e: KeyboardEvent) => {
      // Don't fire when typing in an input
      if ((e.target as HTMLElement).tagName === 'INPUT') return;
      const key = keyMap[e.key];
      if (key) {
        e.preventDefault();
        toggleLayer(key as LayerKey);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleLayer]);

  return (
    <div
      className="panel"
      style={{
        margin: '14px 0 14px 14px',
        padding: '6px 0',
        width: 168,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        userSelect: 'none',
        pointerEvents: 'auto',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '4px 10px 6px',
          fontFamily: 'var(--font-display)',
          fontSize: '0.55rem',
          letterSpacing: '0.2em',
          color: 'rgba(0, 240, 255, 0.45)',
          textTransform: 'uppercase',
          borderBottom: '1px solid rgba(0, 240, 255, 0.12)',
          marginBottom: 2,
        }}
      >
        LAYERS
      </div>

      {/* Toggles */}
      {LAYER_CONFIG.map(({ key, label, color, type, functional, shortcut }) => (
        <LayerToggle
          key={key}
          label={label}
          color={color}
          count={counts[type] ?? 0}
          active={layers[key as LayerKey]}
          functional={functional}
          shortcut={shortcut ?? undefined}
          onToggle={() => functional && toggleLayer(key as LayerKey)}
        />
      ))}

      {/* Footer status */}
      <div
        style={{
          padding: '6px 10px 2px',
          marginTop: 4,
          borderTop: '1px solid rgba(0, 240, 255, 0.12)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.55rem',
          color: 'rgba(0, 240, 255, 0.4)',
          letterSpacing: '0.08em',
        }}
      >
        INTEL FEEDS: {activeCount}/8 ACTIVE
      </div>
    </div>
  );
}

