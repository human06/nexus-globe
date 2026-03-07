/**
 * LayerControls — vertical stack of layer toggles on the left edge.
 * Wired to useGlobeStore; only the Flights layer is fully functional in Epic 1.
 */
import LayerToggle from './LayerToggle';
import { useGlobeStore } from '../../stores/globeStore';

const LAYER_CONFIG = [
  { key: 'flights',    label: 'Flights',    color: '#ffee00', type: 'flight',    functional: true  },
  { key: 'news',       label: 'News',       color: '#00f0ff', type: 'news',      functional: false },
  { key: 'ships',      label: 'Ships',      color: '#00ff88', type: 'ship',      functional: false },
  { key: 'satellites', label: 'Satellites', color: '#ff00aa', type: 'satellite', functional: false },
  { key: 'disasters',  label: 'Disasters',  color: '#ff6600', type: 'disaster',  functional: false },
  { key: 'conflicts',  label: 'Conflicts',  color: '#ff0044', type: 'conflict',  functional: false },
  { key: 'traffic',    label: 'Traffic',    color: '#aa44ff', type: 'traffic',   functional: false },
  { key: 'cameras',    label: 'Cameras',    color: '#888888', type: 'camera',    functional: false },
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

  return (
    <div
      className="panel"
      style={{
        margin: '14px 0 14px 14px',
        padding: '6px 0',
        width: 160,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        userSelect: 'none',
        pointerEvents: 'auto',
      }}
    >
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
      {LAYER_CONFIG.map(({ key, label, color, type, functional }) => (
        <LayerToggle
          key={key}
          label={label}
          color={color}
          count={counts[type] ?? 0}
          active={layers[key as LayerKey]}
          functional={functional}
          onToggle={() => toggleLayer(key as LayerKey)}
        />
      ))}
    </div>
  );
}

