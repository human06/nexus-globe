import { create } from 'zustand';
import type { GlobeEvent, EventType, WSStatus } from '../types/events';

interface LayerVisibility {
  news: boolean;
  flights: boolean;
  ships: boolean;
  satellites: boolean;
  disasters: boolean;
  conflicts: boolean;
  traffic: boolean;
  cameras: boolean;
}

interface GlobeStore {
  // State
  events: Map<string, GlobeEvent>;
  layers: LayerVisibility;
  severityRange: [number, number];
  timeRange: [number, number];
  searchQuery: string;
  selectedEventId: string | null;
  /** WebSocket connection status (driven by useWebSocket hook) */
  wsStatus: WSStatus;

  // Actions
  toggleLayer: (layer: keyof LayerVisibility) => void;
  selectEvent: (id: string | null) => void;
  upsertEvents: (incoming: GlobeEvent[]) => void;
  removeEvent: (id: string) => void;
  removeExpired: () => void;
  setTimeRange: (range: [number, number]) => void;
  setSearchQuery: (query: string) => void;
  setWsStatus: (status: WSStatus) => void;
}

const now = Date.now();
const h24 = 24 * 60 * 60 * 1000;

export const useGlobeStore = create<GlobeStore>((set) => ({
  events: new Map(),
  layers: {
    news: true,
    flights: true,
    ships: true,
    satellites: true,
    disasters: true,
    conflicts: true,
    traffic: true,
    cameras: true,
  },
  severityRange: [1, 5],
  timeRange: [now - h24, now],
  searchQuery: '',
  selectedEventId: null,
  wsStatus: 'disconnected',

  toggleLayer: (layer) =>
    set((state) => ({
      layers: { ...state.layers, [layer]: !state.layers[layer] },
    })),

  selectEvent: (id) => set({ selectedEventId: id }),

  upsertEvents: (incoming) =>
    set((state) => {
      const next = new Map(state.events);
      for (const ev of incoming) {
        next.set(ev.id, ev);
      }
      return { events: next };
    }),

  removeEvent: (id) =>
    set((state) => {
      const next = new Map(state.events);
      next.delete(id);
      return { events: next };
    }),

  removeExpired: () =>
    set((state) => {
      const ts = Date.now();
      const next = new Map(state.events);
      for (const [id, ev] of next) {
        if (ev.expiresAt && ev.expiresAt < ts) {
          next.delete(id);
        }
      }
      return { events: next };
    }),

  setTimeRange: (range) => set({ timeRange: range }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setWsStatus: (status) => set({ wsStatus: status }),
}));

// Convenience type export
export type { GlobeStore, LayerVisibility, EventType };

