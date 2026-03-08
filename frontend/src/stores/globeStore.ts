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

interface FlyToTarget {
  lat: number;
  lng: number;
  altitude?: number;
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
  /** Whether the globe is auto-rotating */
  isAutoRotating: boolean;
  /** Camera fly-to target (set to trigger a smooth pan on the globe) */
  flyToTarget: FlyToTarget | null;
  /** Timeline time-travel mode */
  timeMode: 'live' | 'historical';
  /** Timestamp (ms) currently displayed in historical mode */
  currentViewTime: number;
  /** Whether heatmap density mode is active */
  heatmapMode: boolean;
  /**
   * Current globe camera altitude (Globe.GL "altitude" units; 1.0 = Earth radius).
   * Used by layer components for LOD decisions (fewer markers when zoomed out).
   * Default 2.5 matches the initial pointOfView in GlobeCanvas.
   */
  cameraAltitude: number;

  // Actions
  toggleLayer: (layer: keyof LayerVisibility) => void;
  toggleAutoRotate: () => void;
  selectEvent: (id: string | null) => void;
  upsertEvents: (incoming: GlobeEvent[]) => void;
  removeEvent: (id: string) => void;
  removeExpired: () => void;
  setTimeRange: (range: [number, number]) => void;
  setSeverityRange: (range: [number, number]) => void;
  setSearchQuery: (query: string) => void;
  setWsStatus: (status: WSStatus) => void;
  flyTo: (target: FlyToTarget) => void;
  clearFlyTo: () => void;
  setTimeMode: (mode: 'live' | 'historical') => void;
  setCurrentViewTime: (time: number) => void;
  toggleHeatmapMode: () => void;
  setCameraAltitude: (alt: number) => void;
}

const now = Date.now();
const h24 = 24 * 60 * 60 * 1000;
// Upper bound rolls 24 h ahead so live events are never filtered out
const FUTURE = now + h24;

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
  timeRange: [now - h24, FUTURE],
  searchQuery: '',
  selectedEventId: null,
  wsStatus: 'disconnected',
  isAutoRotating: true,
  flyToTarget: null,
  timeMode: 'live',
  currentViewTime: Date.now(),
  heatmapMode: false,
  cameraAltitude: 2.5,

  toggleAutoRotate: () =>
    set((state) => ({ isAutoRotating: !state.isAutoRotating })),

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

  setSeverityRange: (range) => set({ severityRange: range }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setWsStatus: (status) => set({ wsStatus: status }),

  flyTo: (target) => set({ flyToTarget: target }),

  clearFlyTo: () => set({ flyToTarget: null }),

  setTimeMode: (mode) => set({ timeMode: mode }),

  setCurrentViewTime: (time) => set({ currentViewTime: time }),

  toggleHeatmapMode: () => set((state) => ({ heatmapMode: !state.heatmapMode })),

  setCameraAltitude: (alt) => set({ cameraAltitude: alt }),
}));

// Convenience type export
export type { GlobeStore, LayerVisibility, EventType, FlyToTarget };

