import { useMemo } from 'react';
import { useGlobeStore } from '../stores/globeStore';
import type { EventType, GlobeEvent } from '../types/events';

/**
 * TODO: Hook that returns filtered events for a specific layer type,
 * applying severity, time range, and search filters from the globe store.
 */
export function useLayerData(type: EventType): GlobeEvent[] {
  const events = useGlobeStore((s) => s.events);
  const severityRange = useGlobeStore((s) => s.severityRange);
  const timeRange = useGlobeStore((s) => s.timeRange);
  const searchQuery = useGlobeStore((s) => s.searchQuery);

  return useMemo(() => {
    const result: GlobeEvent[] = [];
    for (const ev of events.values()) {
      if (ev.type !== type) continue;
      if (ev.severity < severityRange[0] || ev.severity > severityRange[1]) continue;
      if (ev.timestamp < timeRange[0] || ev.timestamp > timeRange[1]) continue;
      if (
        searchQuery &&
        !ev.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
        continue;
      result.push(ev);
    }
    return result;
  }, [events, type, severityRange, timeRange, searchQuery]);
}
