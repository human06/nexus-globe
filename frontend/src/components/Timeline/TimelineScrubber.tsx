/**
 * TimelineScrubber — horizontal 7-day timeline bar at the bottom of the screen.
 *
 * Story 3.11:
 * - Drag handle to scrub to any point in the past 7 days
 * - Play/pause button with selectable speed (1x / 10x / 60x / 360x)
 * - "LIVE" button snaps back to real-time
 * - Event density sparkline above the slider
 * - "HISTORICAL MODE — date" shown in HUD (via globeStore.timeMode)
 * - Keyboard: Space (play/pause), ← → (±1h), L (live)
 */
import { useCallback, useRef, useState } from 'react';
import { useTimeTravel } from '../../hooks/useTimeTravel';
import type { PlaybackSpeed } from '../../hooks/useTimeTravel';
import PlaybackControls from './PlaybackControls';
import DensitySparkline from './DensitySparkline';

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function formatDate(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

function formatDateTime(ts: number): string {
  const d = new Date(ts);
  return (
    d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' ' +
    d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) +
    ' UTC'
  );
}

function buildTickLabels(minTime: number, maxTime: number): Array<{ label: string; pct: number }> {
  const ticks: Array<{ label: string; pct: number }> = [];
  const span = maxTime - minTime;
  const start = new Date(minTime);
  start.setUTCHours(0, 0, 0, 0);
  let t = start.getTime();
  while (t <= maxTime) {
    if (t >= minTime) {
      ticks.push({ label: formatDate(t), pct: (t - minTime) / span });
    }
    t += 24 * 60 * 60 * 1000;
  }
  return ticks;
}

export default function TimelineScrubber() {
  const [open, setOpen] = useState(true);

  const {
    timeMode,
    currentViewTime,
    isPlaying,
    playbackSpeed,
    isFetching,
    setPlaybackSpeed,
    scrubTo,
    returnToLive,
    togglePlay,
  } = useTimeTravel();

  const minTime = Date.now() - SEVEN_DAYS_MS;
  const maxTime = Date.now();

  const trackRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);

  const positionFromEvent = useCallback((clientX: number): number => {
    const el = trackRef.current;
    if (!el) return currentViewTime;
    const { left, width } = el.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - left) / width));
    return minTime + pct * (maxTime - minTime);
  }, [minTime, maxTime, currentViewTime]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    void scrubTo(positionFromEvent(e.clientX));
    const onMove = (ev: MouseEvent) => {
      if (isDragging.current) void scrubTo(positionFromEvent(ev.clientX));
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [scrubTo, positionFromEvent]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    isDragging.current = true;
    void scrubTo(positionFromEvent(e.touches[0].clientX));
    const onMove = (ev: TouchEvent) => {
      if (isDragging.current) void scrubTo(positionFromEvent(ev.touches[0].clientX));
    };
    const onEnd = () => {
      isDragging.current = false;
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('touchend', onEnd);
    };
    window.addEventListener('touchmove', onMove);
    window.addEventListener('touchend', onEnd);
  }, [scrubTo, positionFromEvent]);

  const handlePct = timeMode === 'live'
    ? 1
    : Math.max(0, Math.min(1, (currentViewTime - minTime) / (maxTime - minTime)));

  const ticks = buildTickLabels(minTime, maxTime);
  const isLive = timeMode === 'live';

  return (
    <>
      {/* ── Toggle pill — always visible above the news ticker ── */}
      <button
        onClick={() => setOpen((v) => !v)}
        title={open ? 'Hide timeline' : 'Show timeline'}
        style={{
          position: 'fixed',
          bottom: 36,   // 32px ticker + 4px gap
          right: 14,
          zIndex: 35,
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          background: 'rgba(8,8,20,0.82)',
          border: `1px solid rgba(0,240,255,${open ? '0.45' : '0.22'})`,
          borderRadius: 3,
          color: open ? 'var(--neon-cyan)' : 'rgba(0,240,255,0.45)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.6rem',
          letterSpacing: '0.08em',
          padding: '3px 8px',
          cursor: 'pointer',
          backdropFilter: 'blur(6px)',
          transition: 'border-color 0.2s, color 0.2s',
          pointerEvents: 'auto',
          userSelect: 'none',
        }}
      >
        TIMELINE {open ? '▼' : '▲'}
      </button>

      {/* ── Scrubber panel — slides in/out above the news ticker ── */}
      <div
        style={{
          position: 'fixed',
          bottom: 32,   // sit directly on top of the 32px news ticker
          left: 0,
          right: 0,
          zIndex: 29,   // BELOW news ticker (z:30) so it hides behind it when closed
          background: 'rgba(8,8,16,0.88)',
          borderTop: '1px solid rgba(0,240,255,0.18)',
          backdropFilter: 'blur(8px)',
          padding: '4px 14px 6px',
          pointerEvents: open ? 'auto' : 'none',
          userSelect: 'none',
          transform: open ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.22s cubic-bezier(0.4,0,0.2,1)',
        }}
      >
      {/* Sparkline */}
      <div style={{ padding: '2px 0 4px', position: 'relative' }}>
        <DensitySparkline
          minTime={minTime}
          maxTime={maxTime}
          currentTime={isLive ? maxTime : currentViewTime}
          width={typeof window !== 'undefined' ? window.innerWidth - 28 : 1200}
          height={22}
        />
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        style={{
          position: 'relative',
          height: 4,
          background: 'rgba(0,240,255,0.15)',
          borderRadius: 2,
          cursor: 'pointer',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: `${handlePct * 100}%`,
            background: isLive
              ? 'linear-gradient(to right, rgba(0,240,255,0.4), rgba(0,240,255,0.7))'
              : 'linear-gradient(to right, rgba(0,240,255,0.2), rgba(0,240,255,0.5))',
            borderRadius: 2,
            transition: isFetching ? 'none' : 'width 0.08s linear',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: `${handlePct * 100}%`,
            transform: 'translate(-50%, -50%)',
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: isLive ? '#ff2244' : 'var(--neon-cyan)',
            boxShadow: `0 0 8px ${isLive ? '#ff2244' : 'var(--neon-cyan)'}`,
            transition: isFetching ? 'none' : 'left 0.08s linear',
            zIndex: 1,
          }}
        />
      </div>

      {/* Tick labels */}
      <div style={{ position: 'relative', height: 16, marginTop: 2 }}>
        {ticks.map(({ label, pct }) => (
          <span
            key={label}
            style={{
              position: 'absolute',
              left: `${pct * 100}%`,
              transform: 'translateX(-50%)',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.55rem',
              color: 'rgba(0,240,255,0.45)',
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </span>
        ))}
        {!isLive && (
          <span
            style={{
              position: 'absolute',
              left: `${Math.min(handlePct * 100, 80)}%`,
              transform: 'translateX(-50%)',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6rem',
              color: 'var(--neon-cyan)',
              background: 'rgba(0,0,0,0.7)',
              padding: '1px 4px',
              borderRadius: 2,
              whiteSpace: 'nowrap',
              top: -20,
              border: '1px solid rgba(0,240,255,0.25)',
            }}
          >
            {isFetching ? 'LOADING…' : formatDateTime(currentViewTime)}
          </span>
        )}
      </div>

      {/* Transport */}
      <PlaybackControls
        isPlaying={isPlaying}
        playbackSpeed={playbackSpeed as PlaybackSpeed}
        isLive={isLive}
        onTogglePlay={togglePlay}
        onSetSpeed={(s) => setPlaybackSpeed(s)}
        onLive={returnToLive}
        onStepBack={() => void scrubTo(currentViewTime - 60 * 60 * 1000)}
        onStepForward={() => void scrubTo(currentViewTime + 60 * 60 * 1000)}
      />
    </div>
    </>
  );
}
