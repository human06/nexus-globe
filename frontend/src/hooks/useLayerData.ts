import { useMemo } from 'react';
import { useGlobeStore } from '../stores/globeStore';
import type { EventType, GlobeEvent } from '../types/events';

/**
 * Per-layer hard caps — prevents GPU/DOM overload when data volumes are large.
 * Events are ranked by severity DESC, then recency DESC before slicing.
 *
 * These caps represent the maximum number of markers rendered simultaneously.
 * Ships are DOM elements (most expensive), flights are Three.js sprites.
 */
const LAYER_CAPS: Partial<Record<EventType, number>> = {
  flight:    500,   // ADS-B: can be 4 000+ world-wide
  ship:      5000,  // AIS WebGL sprites: GPU-resident, can handle 5 000+ (LOD managed in ShipLayer)
  satellite: 600,   // CelesTrak: ~487 typically — soft cap
  conflict:  400,
  traffic:    80,
  news:      150,
  disaster:  100,
  camera:     50,
};

/**
 * Priority score for a given event — higher = shown first when cap is applied.
 * Severity dominates; recency breaks ties within the same severity bracket.
 */
function priorityScore(ev: GlobeEvent): number {
  // severity ∈ [1,5]; timestamp in Unix ms (~1.7 × 10¹²)
  // Weight: severity × 10¹³ so it always outranks any timestamp contribution.
  return ev.severity * 1e13 + ev.timestamp;
}

/**
 * Returns filtered + capped events for a specific layer type, applying
 * severity, time range, and search filters from the globe store.
 *
 * @param type - The EventType to filter by.
 * @param overrideCap - Optional per-call override for the marker cap.
 *                      Pass `Infinity` to bypass capping entirely.
 */
export function useLayerData(type: EventType, overrideCap?: number): GlobeEvent[] {
  const events        = useGlobeStore((s) => s.events);
  const severityRange = useGlobeStore((s) => s.severityRange);
  const timeRange     = useGlobeStore((s) => s.timeRange);
  const searchQuery   = useGlobeStore((s) => s.searchQuery);

  return useMemo(() => {
    const result: GlobeEvent[] = [];
    for (const ev of events.values()) {
      if (ev.type !== type) continue;
      if (ev.severity < severityRange[0] || ev.severity > severityRange[1]) continue;
      if (ev.timestamp < timeRange[0] || ev.timestamp > timeRange[1]) continue;
      if (searchQuery && !ev.title.toLowerCase().includes(searchQuery.toLowerCase())) continue;
      result.push(ev);
    }

    // Determine effective cap
    const cap = overrideCap !== undefined ? overrideCap : (LAYER_CAPS[type] ?? Infinity);

    if (!Number.isFinite(cap) || result.length <= cap) {
      return result;
    }

    // Sort by priority DESC, then trim to cap
    result.sort((a, b) => priorityScore(b) - priorityScore(a));
    return result.slice(0, cap);
  }, [events, type, severityRange, timeRange, searchQuery, overrideCap]);
}

/** Exported for use in LOD/heatmap components to know the configured cap. */
export { LAYER_CAPS };
