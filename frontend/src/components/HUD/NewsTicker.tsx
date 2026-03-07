/**
 * NewsTicker — cyberpunk scrolling news bar fixed at the bottom of the screen.
 *
 * Features:
 * - Latest 20 news events sorted by timestamp desc, scrolls right-to-left
 * - "BREAKING" prefix on events < 15 min old (Tier 1 RSS)
 * - Multi-source indicator: ✓ dots for confirmation count
 * - Severity-coloured dot per event
 * - Click headline → fly camera to location + open detail panel
 * - Pauses on hover; new headlines flash/glow on entry
 * - "NO ACTIVE FEEDS" fallback
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { useGlobeStore } from '../../stores/globeStore';
import type { GlobeEvent } from '../../types/events';

// ── Constants ──────────────────────────────────────────────────────────────────
const MAX_HEADLINES = 20;
const BREAKING_THRESHOLD_MS = 15 * 60 * 1000; // 15 minutes

const SEV_COLORS: Record<number, string> = {
  1: '#00ff88',
  2: '#ffee00',
  3: '#ff9900',
  4: '#ff4400',
  5: '#ff0044',
};

const SOURCE_BADGES: Record<string, string> = {
  reuters:       'REUTERS',
  ap:            'AP',
  bbc:           'BBC',
  aljazeera:     'AJ',
  france24:      'F24',
  dw:            'DW',
  event_registry:'ER',
  gdelt:         'GDELT',
  rss_wires:     'RSS',
};

// ── Helpers ────────────────────────────────────────────────────────────────────
function timeAgo(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function confirmationDots(metadata: Record<string, unknown>): string {
  const count = (metadata?.confirmation_count as number) ?? 1;
  if (count >= 3) return ' ✓✓✓';
  if (count === 2) return ' ✓✓';
  return '';
}

function sourceBadge(source: string): string {
  return SOURCE_BADGES[source] ?? source.toUpperCase().slice(0, 6);
}

function isBreaking(ev: GlobeEvent): boolean {
  const age = Date.now() - ev.timestamp;
  const src = ev.source;
  return age < BREAKING_THRESHOLD_MS && (
    src === 'rss_wires' || src === 'reuters' || src === 'ap' || src === 'bbc'
  );
}

// ── Component ──────────────────────────────────────────────────────────────────
export default function NewsTicker() {
  const events      = useGlobeStore((s) => s.events);
  const selectEvent = useGlobeStore((s) => s.selectEvent);
  const flyTo       = useGlobeStore((s) => s.flyTo);

  // Latest 20 news events
  const headlines = (() => {
    const news: GlobeEvent[] = [];
    for (const ev of events.values()) {
      if (ev.type === 'news') news.push(ev);
    }
    news.sort((a, b) => b.timestamp - a.timestamp);
    return news.slice(0, MAX_HEADLINES);
  })();

  // Track which IDs are "new" (recently appeared) for flash animation
  const prevIdsRef = useRef(new Set<string>());
  const [newIds, setNewIds]   = useState(new Set<string>());
  const [paused, setPaused]   = useState(false);
  const animRef  = useRef<Animation | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const incoming = new Set(headlines.map((h) => h.id));
    const appeared: string[] = [];
    for (const id of incoming) {
      if (!prevIdsRef.current.has(id)) appeared.push(id);
    }
    prevIdsRef.current = incoming;
    if (appeared.length > 0) {
      setNewIds(new Set(appeared));
      const timer = setTimeout(() => setNewIds(new Set()), 2000);
      return () => clearTimeout(timer);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headlines.length]);

  // CSS marquee via Web Animations API for smooth pausing
  useEffect(() => {
    const track = trackRef.current;
    if (!track || headlines.length === 0) return;
    const totalWidth = track.scrollWidth;
    const duration   = Math.max(20_000, totalWidth * 18);

    animRef.current?.cancel();
    const anim = track.animate(
      [
        { transform: 'translateX(100vw)' },
        { transform: `translateX(-${totalWidth}px)` },
      ],
      { duration, iterations: Infinity, easing: 'linear' },
    );
    animRef.current = anim;
    return () => anim.cancel();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headlines.length]);

  // Pause / resume on hover
  useEffect(() => {
    if (!animRef.current) return;
    if (paused) animRef.current.pause();
    else        animRef.current.play();
  }, [paused]);

  const handleClick = useCallback((ev: GlobeEvent) => {
    selectEvent(ev.id);
    if (ev.latitude != null && ev.longitude != null) {
      flyTo({ lat: ev.latitude, lng: ev.longitude, altitude: 1.8 });
    }
  }, [selectEvent, flyTo]);

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 30,
        height: 32,
        background: 'rgba(6, 6, 18, 0.92)',
        backdropFilter: 'blur(6px)',
        borderTop: '1px solid rgba(0, 240, 255, 0.35)',
        boxShadow: '0 -4px 18px rgba(0, 240, 255, 0.12)',
        display: 'flex',
        alignItems: 'center',
        overflow: 'hidden',
        userSelect: 'none',
        pointerEvents: 'auto',
      }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {/* ── Left label badge ── */}
      <div
        style={{
          flexShrink: 0,
          padding: '0 10px',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          background: 'var(--neon-cyan)',
          color: '#000',
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          fontSize: '0.6rem',
          letterSpacing: '0.2em',
          whiteSpace: 'nowrap',
          zIndex: 1,
          boxShadow: '4px 0 12px rgba(0, 240, 255, 0.3)',
        }}
      >
        INTEL FEED
      </div>

      {/* ── Scrolling track ── */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative', height: '100%' }}>
        {headlines.length === 0 ? (
          <div
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              padding: '0 20px',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.7rem',
                color: 'rgba(0, 240, 255, 0.3)',
                letterSpacing: '0.2em',
              }}
            >
              NO ACTIVE FEEDS
            </span>
          </div>
        ) : (
          <div
            ref={trackRef}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0,
              whiteSpace: 'nowrap',
              height: '100%',
            }}
          >
            {headlines.map((ev) => {
              const isNew     = newIds.has(ev.id);
              const breaking  = isBreaking(ev);
              const sevColor  = SEV_COLORS[ev.severity] ?? '#00f0ff';
              const badge     = sourceBadge(ev.source);
              const dots      = confirmationDots(ev.metadata);
              const ago       = timeAgo(ev.timestamp);
              const feedSrc   = (ev.metadata?.feed_source as string) ?? ev.source;

              return (
                <span
                  key={ev.id}
                  onClick={() => handleClick(ev)}
                  style={{
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '0 22px 0 18px',
                    height: '100%',
                    borderRight: '1px solid rgba(0, 240, 255, 0.12)',
                    animation: isNew ? 'ticker-flash 0.35s ease 4' : undefined,
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLSpanElement).style.background = 'rgba(0, 240, 255, 0.07)';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLSpanElement).style.background = 'transparent';
                  }}
                >
                  {/* Severity dot */}
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      background: sevColor,
                      boxShadow: `0 0 5px ${sevColor}`,
                      flexShrink: 0,
                    }}
                  />

                  {/* BREAKING badge */}
                  {breaking && (
                    <span
                      style={{
                        fontFamily: 'var(--font-display)',
                        fontWeight: 700,
                        fontSize: '0.55rem',
                        color: '#ff2244',
                        letterSpacing: '0.15em',
                        textShadow: '0 0 6px #ff2244',
                        animation: 'nexus-pulse 0.8s ease-in-out infinite',
                      }}
                    >
                      BREAKING
                    </span>
                  )}

                  {/* Category tag */}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.58rem',
                      color: 'rgba(0,240,255,0.45)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                    }}
                  >
                    [{ev.category}]
                  </span>

                  {/* Headline text */}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.72rem',
                      color: isNew ? '#ffffff' : 'rgba(0, 240, 255, 0.88)',
                      textShadow: isNew ? '0 0 10px #00f0ff' : undefined,
                      letterSpacing: '0.02em',
                    }}
                  >
                    {ev.title}
                  </span>

                  {/* Confirmation dots */}
                  {dots && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.65rem',
                        color: '#00ff88',
                        textShadow: '0 0 4px #00ff88',
                      }}
                    >
                      {dots}
                    </span>
                  )}

                  {/* Time ago */}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.6rem',
                      color: 'rgba(0,240,255,0.33)',
                    }}
                  >
                    {ago}
                  </span>

                  {/* Source badge */}
                  <span
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: '0.5rem',
                      letterSpacing: '0.12em',
                      color: '#000',
                      background: 'rgba(0,240,255,0.75)',
                      borderRadius: 2,
                      padding: '1px 4px',
                      flexShrink: 0,
                    }}
                  >
                    {SOURCE_BADGES[feedSrc] ?? badge}
                  </span>
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
