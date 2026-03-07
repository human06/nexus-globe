/**
 * SatelliteLayer — renders live CelesTrak satellite positions on Globe.GL.
 *
 * Visuals:
 *  - Neon magenta (#ff00aa) point markers for all satellites, altitude-accurate
 *  - ISS / Tiangong / CSS: larger white dots with stronger glow
 *  - Starlink constellation: small violet dots
 *  - Military sats: red dots; weather sats: blue; GPS: yellow
 *  - Orbital arc trails drawn with arcsData (forward 90-min path, 18 points)
 *  - Selected satellite: cyan (#00e5ff), larger, pulsing ring
 *  - Layer hides when satellites toggle is off
 *
 * Writes into pointMarkerStore (satellite key) — merged by PointsLayerSync,
 * ArcsLayerSync, RingsLayerSync into the single globe.gl channels.
 *
 * Data from useLayerData('satellite') ← WebSocket 'celestrak' channel.
 * Trail: [{lat, lng}, …] (18 points × 5 min forward from current position).
 */
import { useEffect } from 'react';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import { usePointMarkerStore } from '../pointMarkerStore';
import type { PointDatum, ArcDatum, RingDatum } from '../pointMarkerStore';
import type { GlobeEvent } from '../../../types/events';

// ── Tooltip factory ───────────────────────────────────────────────────────────

function buildLabel(ev: GlobeEvent): string {
  const meta    = ev.metadata as Record<string, unknown>;
  const norad   = String(meta?.norad_id ?? '—');
  const alt     = ev.altitude != null ? `${Math.round(ev.altitude / 1000)} km` : '—';
  const speed   = ev.speed    != null ? `${Math.round(ev.speed)} km/h` : '—';
  const inc     = meta?.inclination_deg != null ? `${Number(meta.inclination_deg).toFixed(1)}°` : '—';
  const country = String(meta?.country_code ?? '—');
  const group   = String(meta?.group ?? ev.category ?? '—');
  const period  = meta?.period_min != null ? `${Number(meta.period_min).toFixed(1)} min` : '—';

  return `
    <div style="
      background:rgba(0,0,0,.92);border:1px solid #ff00aa;
      padding:6px 10px;font:11px/1.6 'JetBrains Mono',monospace;
      color:#ff88dd;border-radius:2px;pointer-events:none;min-width:180px;
    ">
      <b style="font-size:12px;color:#ff00aa;letter-spacing:.05em">${ev.title}</b><br/>
      Alt: ${alt} &nbsp; Speed: ${speed}<br/>
      Period: ${period} &nbsp; Inc: ${inc}<br/>
      <span style="color:rgba(255,0,170,.55)">NORAD ${norad} · ${country} · ${group}</span>
    </div>`;
}

// Resolve per-category color for globe.gl pointColor
function satColor(ev: GlobeEvent, selectedId: string | null): string {
  if (ev.id === selectedId) return '#00e5ff';
  const cat = (ev.category ?? '').toLowerCase();
  if (cat === 'stations' || cat === 'station') return '#ffffff';
  if (cat === 'starlink') return '#cc66ff';
  if (cat === 'military' || cat === 'military-sats') return '#ff3333';
  if (cat === 'weather' || cat === 'weather-sats') return '#44bbff';
  if (cat === 'gps-ops' || cat === 'gps' || cat === 'navigation') return '#ffee44';
  if (cat === 'resource' || cat === 'earth-observation') return '#44ffaa';
  if (cat === 'amateur') return '#ff9944';
  return '#ff00aa';
}

// Resolve per-category radius for globe.gl pointRadius
function satRadius(ev: GlobeEvent, selectedId: string | null): number {
  if (ev.id === selectedId) return 0.9;
  const cat = (ev.category ?? '').toLowerCase();
  if (cat === 'stations' || cat === 'station') return 0.65;
  if (cat === 'starlink') return 0.18;
  return 0.35;
}

// Orbital arc color gradient [startColor, endColor] based on category
function arcColor(cat: string, selected: boolean): [string, string] {
  if (selected) return ['rgba(0,229,255,0.85)', 'rgba(0,229,255,0.05)'];
  if (cat === 'stations' || cat === 'station')
    return ['rgba(255,255,255,0.7)', 'rgba(255,0,170,0.03)'];
  if (cat === 'starlink')
    return ['rgba(204,102,255,0.35)', 'rgba(204,102,255,0.0)'];
  if (cat === 'military' || cat === 'military-sats')
    return ['rgba(255,50,50,0.45)', 'rgba(255,50,50,0.0)'];
  return ['rgba(255,0,170,0.5)', 'rgba(255,0,170,0.0)'];
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SatelliteLayer() {
  const satellites      = useLayerData('satellite');
  const isVisible       = useGlobeStore((s) => s.layers.satellites);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);

  const setPoints = usePointMarkerStore((s) => s.setPoints);
  const setArcs   = usePointMarkerStore((s) => s.setArcs);
  const setRings  = usePointMarkerStore((s) => s.setRings);

  // Listen for globe-point-click events dispatched by PointsLayerSync
  useEffect(() => {
    const handler = (e: Event) => {
      const pd = (e as CustomEvent<PointDatum>).detail;
      if (pd.layerKey === 'satellite') selectEvent(pd.ev.id);
    };
    window.addEventListener('globe-point-click', handler);
    return () => window.removeEventListener('globe-point-click', handler);
  }, [selectEvent]);

  // ── Point markers ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isVisible) {
      setPoints('satellite', []);
      return;
    }
    const data: PointDatum[] = satellites.map((ev) => ({
      ev,
      lat:      ev.latitude,
      lng:      ev.longitude,
      alt:      Math.max(0.002, (ev.altitude ?? 400_000) / 6_371_000),
      radius:   satRadius(ev, selectedEventId),
      color:    satColor(ev, selectedEventId),
      label:    buildLabel(ev),
      layerKey: 'satellite' as const,
    }));
    setPoints('satellite', data);
  }, [satellites, isVisible, selectedEventId, setPoints]);

  // ── Orbital arc trails ────────────────────────────────────────────────────
  useEffect(() => {
    if (!isVisible || satellites.length === 0) {
      setArcs('satellite', []);
      return;
    }
    const arcs: ArcDatum[] = [];
    for (const ev of satellites) {
      if (!ev.trail || ev.trail.length < 2) continue;
      const cat      = (ev.category ?? '').toLowerCase();
      const selected = ev.id === selectedEventId;
      const [cStart, cEnd] = arcColor(cat, selected);
      for (let i = 0; i < ev.trail.length - 1; i++) {
        const p0 = ev.trail[i];
        const p1 = ev.trail[i + 1];
        arcs.push({
          startLat: p0.lat, startLng: p0.lng,
          endLat:   p1.lat, endLng:   p1.lng,
          color:    [cStart, cEnd],
          stroke:   selected ? 0.3 : 0.15,
          altitude: 0.003,
          dashLen:  0.5,
          dashGap:  0.2,
          animTime: selected ? 2500 : 5000,
          layerKey: 'satellite' as const,
        });
      }
    }
    setArcs('satellite', arcs);
  }, [satellites, isVisible, selectedEventId, setArcs]);

  // ── Pulsing ring for selected satellite ──────────────────────────────────
  useEffect(() => {
    const sel = selectedEventId
      ? satellites.find((ev) => ev.id === selectedEventId) ?? null
      : null;

    if (!sel || !isVisible) {
      setRings('satellite', []);
      return;
    }

    const ring: RingDatum = {
      lat:       sel.latitude,
      lng:       sel.longitude,
      maxRadius: 4.0,
      color:     (t: number) => `rgba(0,229,255,${Math.max(0, 1 - t * 1.3)})`,
      speed:     1.2,
      period:    1000,
      layerKey:  'satellite' as const,
    };
    setRings('satellite', [ring]);
  }, [satellites, isVisible, selectedEventId, setRings]);

  return null;
}
