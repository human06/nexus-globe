/**
 * htmlMarkersStore — shared Zustand slice for all HTML marker layers.
 *
 * Globe.GL only exposes one `htmlElementsData` slot per instance.  Each layer
 * that needs HTML markers (News, Disaster, …) registers its datum array here.
 * `HtmlLayerSync` reads the combined array and makes the single globe call.
 */
import { create } from 'zustand';

// ── Shared datum type ────────────────────────────────────────────────────────

export interface HtmlMarkerDatum {
  el:   HTMLElement;
  lat:  number;
  lng:  number;
  alt?: number;
}

// ── Store ────────────────────────────────────────────────────────────────────

type LayerKey = 'news' | 'disaster' | 'ship';

interface HtmlMarkersStore {
  layers: Record<LayerKey, HtmlMarkerDatum[]>;
  setLayer: (key: LayerKey, data: HtmlMarkerDatum[]) => void;
}

export const useHtmlMarkersStore = create<HtmlMarkersStore>((set) => ({
  layers: { news: [], disaster: [], ship: [] },
  setLayer: (key, data) =>
    set((s) => ({ layers: { ...s.layers, [key]: data } })),
}));
