/**
 * PlaybackControls — transport buttons for the timeline scrubber.
 *
 * Story 3.11: ◄ step-back  ▶/⏸ play  ► step-forward  speed selector  ● LIVE
 */
import type { PlaybackSpeed } from '../../hooks/useTimeTravel';

interface PlaybackControlsProps {
  isPlaying: boolean;
  playbackSpeed: PlaybackSpeed;
  isLive: boolean;
  onTogglePlay: () => void;
  onSetSpeed: (s: PlaybackSpeed) => void;
  onLive: () => void;
  onStepBack: () => void;
  onStepForward: () => void;
}

const SPEEDS: PlaybackSpeed[] = [1, 10, 60, 360];
const SPEED_LABELS: Record<PlaybackSpeed, string> = { 1: '1×', 10: '10×', 60: '60×', 360: '360×' };

const btnBase: React.CSSProperties = {
  background: 'none',
  border: '1px solid rgba(0,240,255,0.25)',
  borderRadius: 3,
  color: 'var(--neon-cyan)',
  fontFamily: 'var(--font-mono)',
  fontSize: '0.7rem',
  padding: '2px 7px',
  cursor: 'pointer',
  letterSpacing: '0.05em',
  transition: 'border-color 0.15s, background 0.15s',
};

const activeBtn: React.CSSProperties = {
  ...btnBase,
  background: 'rgba(0,240,255,0.15)',
  border: '1px solid var(--neon-cyan)',
};

export default function PlaybackControls({
  isPlaying,
  playbackSpeed,
  isLive,
  onTogglePlay,
  onSetSpeed,
  onLive,
  onStepBack,
  onStepForward,
}: PlaybackControlsProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        padding: '4px 0',
        userSelect: 'none',
      }}
    >
      <button style={btnBase} onClick={onStepBack} title="Step back 1h (←)">◄</button>
      <button
        style={isPlaying ? activeBtn : btnBase}
        onClick={onTogglePlay}
        title="Play/Pause (Space)"
      >
        {isPlaying ? '⏸' : '▶'}
      </button>
      <button style={btnBase} onClick={onStepForward} title="Step forward 1h (→)">►</button>

      <div style={{ display: 'flex', gap: 3, marginLeft: 6 }}>
        {SPEEDS.map((s) => (
          <button
            key={s}
            style={playbackSpeed === s ? activeBtn : btnBase}
            onClick={() => onSetSpeed(s)}
            title={`Speed ${SPEED_LABELS[s]}`}
          >
            {SPEED_LABELS[s]}
          </button>
        ))}
      </div>

      <button
        style={{
          ...btnBase,
          marginLeft: 10,
          border: `1px solid ${isLive ? '#ff2244' : 'rgba(255,34,68,0.3)'}`,
          color: isLive ? '#ff2244' : 'rgba(255,34,68,0.4)',
          background: isLive ? 'rgba(255,34,68,0.1)' : 'none',
          textShadow: isLive ? '0 0 8px #ff2244' : 'none',
          fontWeight: isLive ? 700 : 400,
        }}
        onClick={onLive}
        title="Return to live (L)"
      >
        ● LIVE
      </button>
    </div>
  );
}
