/**
 * pointMarkerStore — shared Zustand store for all point/arc/ring marker layers.
 *
 * Globe.GL only exposes one `pointsData`, `arcsData`, and `ringsData` slot per
 * instance. Each layer registers its data here. The three sync components
 * (PointsLayerSync, ArcsLayerSync, RingsLayerSync) merge all registered arrays
 * and make the single globe call.
 *
 * Layers that use this store:
 *  - SatelliteLayer  → key 'satellite'
 *  - ConflictLayer   → key 'conflict'
 *  - TrafficLayer    → key 'traffic'
 */
import { create } from 'zustand';
import type { GlobeEvent } from '../../types/events';

// ── Point datum (globe.pointsData) ───────────────────────────────────────────

export interface PointDatum {
  ev:       GlobeEvent;
  lat:      number;
  lng:      number;
  alt:      number;
  radius:   number;
  color:    string;
  label:    string;
  layerKey: PointLayerKey;
}

export type PointLayerKey = 'satellite' | 'conflict' | 'traffic';

// ── Arc datum (globe.arcsData) ────────────────────────────────────────────────

export interface ArcDatum {
  startLat:  number;
  startLng:  number;
  endLat:    number;
  endLng:    number;
  color:     [string, string]; // [start, end] gradient
  stroke:    number;
  altitude:  number;
  dashLen:   number;
  dashGap:   number;
  animTime:  number;
  layerKey:  ArcLayerKey;
}

export type ArcLayerKey = 'satellite' | 'flight_sel';

// ── Ring datum (globe.ringsData) ──────────────────────────────────────────────

export interface RingDatum {
  lat:         number;
  lng:         number;
  maxRadius:   number;
  color:       (t: number) => string;
  speed:       number;
  period:      number;
  layerKey:    RingLayerKey;
}

export type RingLayerKey = 'satellite' | 'conflict' | 'traffic' | 'flight';

// ── Store ─────────────────────────────────────────────────────────────────────

interface PointMarkerStore {
  points: Record<PointLayerKey, PointDatum[]>;
  arcs:   Record<ArcLayerKey,   ArcDatum[]>;
  rings:  Record<RingLayerKey,  RingDatum[]>;

  setPoints: (key: PointLayerKey, data: PointDatum[]) => void;
  setArcs:   (key: ArcLayerKey,   data: ArcDatum[])   => void;
  setRings:  (key: RingLayerKey,  data: RingDatum[])  => void;
}

export const usePointMarkerStore = create<PointMarkerStore>((set) => ({
  points: { satellite: [], conflict: [], traffic: [] },
  arcs:   { satellite: [], flight_sel: [] },
  rings:  { satellite: [], conflict: [], traffic: [], flight: [] },

  setPoints: (key, data) =>
    set((s) => ({ points: { ...s.points, [key]: data } })),
  setArcs: (key, data) =>
    set((s) => ({ arcs: { ...s.arcs, [key]: data } })),
  setRings: (key, data) =>
    set((s) => ({ rings: { ...s.rings, [key]: data } })),
}));
