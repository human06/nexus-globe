/**
 * LayerToggle — single row in the layer control sidebar.
 *
 * Story 2.14: added `shortcut` prop (keyboard key label shown inline)
 * and "SOON" badge for non-functional layers.
 */
interface LayerToggleProps {
  label: string;
  color: string;
  count: number;
  active: boolean;
  functional?: boolean;
  shortcut?: string;
  onToggle: () => void;
}

export default function LayerToggle({
  label,
  color,
  count,
  active,
  functional = false,
  shortcut,
  onToggle,
}: LayerToggleProps) {
  return (
    <button
      onClick={onToggle}
      title={functional ? (shortcut ? `Toggle (key: ${shortcut})` : undefined) : 'Coming soon'}
      disabled={!functional}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '7px',
        width: '100%',
        padding: '5px 10px',
        background: 'transparent',
        border: 'none',
        cursor: functional ? 'pointer' : 'not-allowed',
        opacity: active ? 1 : functional ? 0.35 : 0.22,
        transition: 'opacity 0.15s, filter 0.15s',
        filter: (active && functional) ? `drop-shadow(0 0 4px ${color})` : 'none',
      }}
    >
      {/* Colored dot */}
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: (active && functional) ? color : '#333',
          flexShrink: 0,
          boxShadow: (active && functional) ? `0 0 6px ${color}` : 'none',
          transition: 'background 0.15s',
        }}
      />

      {/* Label */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: (active && functional) ? color : functional ? '#555' : '#333',
          letterSpacing: '0.08em',
          flex: 1,
          textAlign: 'left',
          whiteSpace: 'nowrap',
          transition: 'color 0.15s',
        }}
      >
        {label}
      </span>

      {/* Coming soon badge */}
      {!functional && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.48rem',
            color: '#444',
            letterSpacing: '0.05em',
            border: '1px solid #333',
            borderRadius: 2,
            padding: '0 3px',
          }}
        >
          SOON
        </span>
      )}

      {/* Shortcut key hint (functional layers only) */}
      {functional && shortcut && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.55rem',
            color: active ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.18)',
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 2,
            padding: '0 4px',
            lineHeight: '1.5',
            flexShrink: 0,
          }}
        >
          {shortcut}
        </span>
      )}

      {/* Event count */}
      {functional && (
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.65rem',
            color: active ? 'rgba(255,255,255,0.5)' : '#333',
            minWidth: '3ch',
            textAlign: 'right',
          }}
        >
          {count > 0 ? count.toLocaleString() : '—'}
        </span>
      )}
    </button>
  );
}

