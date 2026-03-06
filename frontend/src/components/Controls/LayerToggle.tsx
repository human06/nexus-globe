/**
 * LayerToggle — single row in the layer control sidebar.
 */
interface LayerToggleProps {
  label: string;
  color: string;
  count: number;
  active: boolean;
  functional?: boolean;
  onToggle: () => void;
}

export default function LayerToggle({
  label,
  color,
  count,
  active,
  functional = false,
  onToggle,
}: LayerToggleProps) {
  return (
    <button
      onClick={onToggle}
      title={functional ? undefined : 'Coming soon'}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        width: '100%',
        padding: '5px 10px',
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        opacity: active ? 1 : 0.35,
        transition: 'opacity 0.15s, filter 0.15s',
        filter: active ? `drop-shadow(0 0 4px ${color})` : 'none',
      }}
    >
      {/* Colored dot */}
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: active ? color : '#444',
          flexShrink: 0,
          boxShadow: active ? `0 0 6px ${color}` : 'none',
          transition: 'background 0.15s',
        }}
      />
      {/* Label */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: active ? color : '#666',
          letterSpacing: '0.08em',
          flex: 1,
          textAlign: 'left',
          whiteSpace: 'nowrap',
          transition: 'color 0.15s',
        }}
      >
        {label}
      </span>
      {/* Event count */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.65rem',
          color: active ? 'rgba(255,255,255,0.55)' : '#444',
          minWidth: '3ch',
          textAlign: 'right',
        }}
      >
        {count > 0 ? count.toLocaleString() : '—'}
      </span>
    </button>
  );
}

