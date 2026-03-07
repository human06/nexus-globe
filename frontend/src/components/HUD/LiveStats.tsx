/**
 * LiveStats — top-right event count per layer + meta-status rows.
 *
 * Story 2.14 updates:
 * - Shows counts for all layers with data (colour-coded)
 * - "NEWS TIERS: N/3 ONLINE" deduced from which news sources have events
 * - AI status pulled from /api/ai/status (polled every 60s)
 */
import { useEffect, useState } from 'react';
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

// News tiers by source name prefix
const TIER_SOURCES = [
  ['rss_wires', 'reuters', 'ap', 'bbc', 'aljazeera', 'france24', 'dw'],  // Tier 1
  ['event_registry'],                                                      // Tier 2
  ['gdelt'],                                                               // Tier 3
];
const TIER_LABELS = ['RSS', 'ER', 'GDELT'];

interface AIStatus {
  status: 'ok' | 'error' | 'unconfigured';
  model?: string;
}

export default function LiveStats() {
  const events = useGlobeStore((s) => s.events);
  const [aiStatus, setAiStatus] = useState<AIStatus | null>(null);
  const [newsExpanded, setNewsExpanded] = useState(false);

  // Poll AI status endpoint
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch('/api/ai/status');
        if (res.ok) {
          const data = await res.json() as AIStatus;
          setAiStatus(data);
        }
      } catch {
        // ignore — backend might not have this endpoint yet
      }
    };
    fetchStatus();
    const id = setInterval(fetchStatus, 60_000);
    return () => clearInterval(id);
  }, []);

  // Count events per type
  const counts: Record<string, number> = {};
  const newsSources = new Set<string>();
  const tierCounts = [0, 0, 0];
  for (const ev of events.values()) {
    counts[ev.type] = (counts[ev.type] ?? 0) + 1;
    if (ev.type === 'news') {
      newsSources.add(ev.source);
      for (let i = 0; i < TIER_SOURCES.length; i++) {
        if (TIER_SOURCES[i].some((src) => ev.source === src || ev.source.startsWith(src))) {
          tierCounts[i]++;
          break;
        }
      }
    }
  }

  // Count which news tiers are online (have at least one event)
  const tiersOnline = TIER_SOURCES.filter((tier) =>
    tier.some((src) => newsSources.has(src)),
  ).length;

  const order = ['flight', 'news', 'ship', 'satellite', 'disaster', 'conflict', 'traffic', 'camera'];
  const active = order.filter((t) => (counts[t] ?? 0) > 0);

  const aiColor  = aiStatus?.status === 'ok' ? '#00ff88' : aiStatus?.status === 'error' ? '#ff2244' : '#666';
  const aiLabel  = aiStatus?.status === 'ok'
    ? `AI: ${(aiStatus.model ?? '').split('/').pop() ?? 'AI'} ●`
    : aiStatus?.status === 'error'
    ? 'AI: ERROR ●'
    : null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: '3px',
      }}
    >
      {/* Event counts row */}
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
        {active.map((type) =>
          type === 'news' ? (
            <button
              key={type}
              onClick={() => setNewsExpanded((x) => !x)}
              title="Toggle news source breakdown"
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                color: LAYER_COLORS[type] ?? '#fff',
                textShadow: `0 0 6px ${LAYER_COLORS[type] ?? '#fff'}`,
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                pointerEvents: 'auto',
              }}
            >
              {LAYER_ICONS[type] ?? '●'} {(counts[type] ?? 0).toLocaleString()}
            </button>
          ) : (
            <span
              key={type}
              style={{
                color: LAYER_COLORS[type] ?? '#fff',
                textShadow: `0 0 6px ${LAYER_COLORS[type] ?? '#fff'}`,
              }}
            >
              {LAYER_ICONS[type] ?? '●'} {(counts[type] ?? 0).toLocaleString()}
            </span>
          ),
        )}
      </div>

      {/* News source breakdown (expandable) */}
      {newsExpanded && (counts['news'] ?? 0) > 0 && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6rem',
            color: 'rgba(0,240,255,0.65)',
            letterSpacing: '0.05em',
            textAlign: 'right',
          }}
        >
          {TIER_LABELS.map((label, i) => `${tierCounts[i]} ${label}`).join(' • ')}
        </div>
      )}

      {/* News tiers status */}
      {newsSources.size > 0 && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6rem',
            color: tiersOnline > 0 ? 'rgba(0,240,255,0.55)' : 'rgba(255,34,68,0.6)',
            letterSpacing: '0.06em',
          }}
        >
          NEWS TIERS: {tiersOnline}/3 ONLINE
        </div>
      )}

      {/* AI status */}
      {aiLabel && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6rem',
            color: aiColor,
            textShadow: `0 0 5px ${aiColor}`,
            letterSpacing: '0.06em',
          }}
        >
          {aiLabel}
        </div>
      )}
    </div>
  );
}

