/**
 * LiveStats — top-right event count per layer.
 * Only shows layers with at least one event.
 */
import { useGlobeStore } from '../../stores/globeStore';

const LAYER_ICONS: Record<string, string> = {
  flight:    '✈',
  news:      '📰',
  ship:      '🚢',
  satellite: '🛰',
  disaster:  '🌋',
  conflict:  '⚔',
  traffic:   '🚦',
  camera:    '📷',
};

const LAYER_COLORS: Record<string, string> = {
  flight:    '#ffee00',
  news:      '#00f0ff',
  ship:      '#00ff88',
  satellite: '#ff00aa',
  disaster:  '#ff6600',
  conflict:  '#ff0044',
  traffic:   '#aa44ff',
  camera:    '#888888',
};

export default function LiveStats() {
  const events = useGlobeStore((s) => s.events);

  // Count events per type
  const counts: Record<string, number> = {};
  for (const ev of events.values()) {
    counts[ev.type] = (counts[ev.type] ?? 0) + 1;
  }

  const order = ['flight', 'news', 'ship', 'satellite', 'disaster', 'conflict', 'traffic', 'camera'];
  const active = order.filter((t) => (counts[t] ?? 0) > 0);

  return (
    <div
      style={{
        display: 'flex',
        gap: '0.75rem',
        alignItems: 'center',
        flexWrap: 'wrap',
        justifyContent: 'flex-end',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.8rem',
      }}
    >
      {active.map((type) => (
        <span
          key={type}
          style={{
            color: LAYER_COLORS[type] ?? '#fff',
            textShadow: `0 0 6px ${LAYER_COLORS[type] ?? '#fff'}`,
          }}
        >
          {LAYER_ICONS[type] ?? '●'} {(counts[type] ?? 0).toLocaleString()}
        </span>
      ))}
    </div>
  );
}

