/**
 * PointsLayerSync — owns the Globe.GL `pointsData` slot.
 * Merges satellite + conflict + traffic point arrays from pointMarkerStore.
 *
 * ArcsLayerSync  — owns the Globe.GL `arcsData` slot.
 * Merges satellite orbital arcs + flight selection arc.
 *
 * RingsLayerSync — owns the Globe.GL `ringsData` slot.
 * Merges satellite + conflict + traffic + flight pulsing rings.
 *
 * Mount exactly once inside <GlobeContext.Provider>, after all layers.
 */
import { useEffect } from 'react';
import { useGlobe } from './GlobeContext';
import {
  usePointMarkerStore,
  type PointDatum,
  type ArcDatum,
  type RingDatum,
} from './pointMarkerStore';

// ── PointsLayerSync ───────────────────────────────────────────────────────────

export function PointsLayerSync() {
  const globe  = useGlobe();
  const points = usePointMarkerStore((s) => s.points);

  useEffect(() => {
    if (!globe) return;

    const combined: PointDatum[] = [
      ...points.satellite,
      ...points.conflict,
      ...points.traffic,
    ];

    globe
      .pointsData(combined)
      .pointLat((d: object) => (d as PointDatum).lat)
      .pointLng((d: object) => (d as PointDatum).lng)
      .pointAltitude((d: object) => (d as PointDatum).alt)
      .pointRadius((d: object) => (d as PointDatum).radius)
      .pointColor((d: object) => (d as PointDatum).color)
      .pointResolution(8)
      .pointsMerge(false)
      .onPointClick((d: object) => {
        const pd = d as PointDatum;
        // Dispatch click via custom event so the layer component can handle it
        window.dispatchEvent(new CustomEvent('globe-point-click', { detail: pd }));
      })
      .pointLabel((d: object) => (d as PointDatum).label);
  }, [globe, points]);

  return null;
}

// ── ArcsLayerSync ─────────────────────────────────────────────────────────────

export function ArcsLayerSync() {
  const globe = useGlobe();
  const arcs  = usePointMarkerStore((s) => s.arcs);

  useEffect(() => {
    if (!globe) return;

    const combined: ArcDatum[] = [
      ...arcs.satellite,
      ...arcs.flight_sel,
    ];

    if (combined.length === 0) {
      globe.arcsData([]);
      return;
    }

    globe
      .arcsData(combined)
      .arcStartLat((d: object) => (d as ArcDatum).startLat)
      .arcStartLng((d: object) => (d as ArcDatum).startLng)
      .arcEndLat((d: object)   => (d as ArcDatum).endLat)
      .arcEndLng((d: object)   => (d as ArcDatum).endLng)
      .arcAltitude((d: object) => (d as ArcDatum).altitude)
      .arcAltitudeAutoScale(false)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .arcColor(((d: object) => (d as ArcDatum).color) as unknown as (d: object) => string)
      .arcStroke((d: object) => (d as ArcDatum).stroke)
      .arcDashLength((d: object) => (d as ArcDatum).dashLen)
      .arcDashGap((d: object) => (d as ArcDatum).dashGap)
      .arcDashAnimateTime((d: object) => (d as ArcDatum).animTime);
  }, [globe, arcs]);

  return null;
}

// ── RingsLayerSync ────────────────────────────────────────────────────────────

export function RingsLayerSync() {
  const globe = useGlobe();
  const rings = usePointMarkerStore((s) => s.rings);

  useEffect(() => {
    if (!globe) return;

    const combined: RingDatum[] = [
      ...rings.satellite,
      ...rings.conflict,
      ...rings.traffic,
      ...rings.flight,
    ];

    if (combined.length === 0) {
      globe.ringsData([]);
      return;
    }

    globe
      .ringsData(combined)
      .ringLat((d: object) => (d as RingDatum).lat)
      .ringLng((d: object) => (d as RingDatum).lng)
      .ringMaxRadius((d: object) => (d as RingDatum).maxRadius)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .ringColor(((d: object) => (d as RingDatum).color) as any)
      .ringPropagationSpeed((d: object) => (d as RingDatum).speed)
      .ringRepeatPeriod((d: object) => (d as RingDatum).period);
  }, [globe, rings]);

  return null;
}
