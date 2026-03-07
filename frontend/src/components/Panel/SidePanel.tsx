/**
 * SidePanel — slides in from the right when an event is selected.
 * Uses CSS transitions; framer-motion not needed for this simple slide.
 */
import EventDetail from './EventDetail';
import { useGlobeStore } from '../../stores/globeStore';

export default function SidePanel() {
  const selectedId  = useGlobeStore((s) => s.selectedEventId);
  const events      = useGlobeStore((s) => s.events);
  const selectEvent = useGlobeStore((s) => s.selectEvent);

  const selected = selectedId ? events.get(selectedId) ?? null : null;
  const isOpen   = selected !== null;

  return (
    <div
      style={{
        position: 'relative',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        className="panel"
        style={{
          width: 270,
          maxHeight: '80vh',
          overflowY: 'auto',
          padding: '14px 16px',
          margin: '14px 14px 14px 0',
          transition: 'transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s',
          transform: isOpen ? 'translateX(0)' : 'translateX(310px)',
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
          position: 'relative',
        }}
      >
        {/* Close button */}
        <button
          onClick={() => selectEvent(null)}
          style={{
            position: 'absolute',
            top: 8,
            right: 10,
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            color: 'rgba(0, 240, 255, 0.55)',
            fontFamily: 'var(--font-mono)',
            fontSize: '1rem',
            lineHeight: 1,
            padding: '2px 4px',
            transition: 'color 0.15s',
          }}
          aria-label="Close panel"
          onMouseEnter={(e) => ((e.currentTarget as HTMLButtonElement).style.color = '#00f0ff')}
          onMouseLeave={(e) => ((e.currentTarget as HTMLButtonElement).style.color = 'rgba(0, 240, 255, 0.55)')}
        >
          ✕
        </button>

        {selected && <EventDetail event={selected} />}
      </div>
    </div>
  );
}

