/**
 * TrafficLayer — renders real-time city traffic congestion on Globe.GL.
 *
 * Visuals:
 *  - City dots color-coded by congestion level:
 *      Free flow   (0–10%):  green  #00cc44
 *      Light       (10–30%): yellow-green #aadd00
 *      Moderate    (30–50%): yellow #ffdd00
 *      Heavy       (50–70%): orange #ff8800
 *      Gridlock    (70%+):   red    #ff2222
 *  - Size reflects severity (larger = more congested)
 *  - Selected city: cyan (#00e5ff), pulsing ring
 *  - HTML tooltip: city name, speed vs free-flow, congestion %, condition
 *  - Layer hides when traffic toggle is off
 *
 * Writes into pointMarkerStore (traffic key) — merged by PointsLayerSync,
 * RingsLayerSync into the single globe.gl channels.
 *
 * Data: useLayerData('traffic') ← WebSocket 'traffic' channel (every 2 min).
 * Metadata: city_name, avg_speed_kmh, free_flow_speed_kmh, congestion_percent,
 *           road_closure_count, confidence, is_demo.
 */
import { useEffect } from 'react';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import { usePointMarkerStore } from '../pointMarkerStore';
import type { PointDatum, RingDatum } from '../pointMarkerStore';
import type { GlobeEvent } from '../../../types/events';

// ── Color helpers ─────────────────────────────────────────────────────────────

function trafficColor(ev: GlobeEvent, selectedId: string | null): string {
  if (ev.id === selectedId) return '#00e5ff';
  const meta        = ev.metadata as Record<string, unknown>;
  const congestion  = Number(meta?.congestion_percent ?? 0);
  if (congestion >= 70) return '#ff2222'; // gridlock — red
  if (congestion >= 50) return '#ff8800'; // heavy     — orange
  if (congestion >= 30) return '#ffdd00'; // moderate  — yellow
  if (congestion >= 10) return '#aadd00'; // light     — yellow-green
  return '#00cc44';                       // free flow — green
}

function trafficRadius(ev: GlobeEvent, selectedId: string | null): number {
  if (ev.id === selectedId) return 1.2;
  // Bigger = more congested city; base size also reflects severity
  const meta       = ev.metadata as Record<string, unknown>;
  const congestion = Number(meta?.congestion_percent ?? 0);
  return 0.2 + (congestion / 100) * 0.7;
}

// ── Tooltip factory ───────────────────────────────────────────────────────────

function buildLabel(ev: GlobeEvent): string {
  const meta        = ev.metadata as Record<string, unknown>;
  const cityName    = String(meta?.city_name       ?? ev.title);
  const speed       = Number(meta?.avg_speed_kmh   ?? 0);
  const freeFlow    = Number(meta?.free_flow_speed_kmh ?? 80);
  const congestion  = Number(meta?.congestion_percent ?? 0);
  const roadClosure = Number(meta?.road_closure_count ?? 0) > 0;
  const isDemo      = meta?.is_demo ? ' <span style="color:#555">[demo]</span>' : '';

  // Color-coded congestion pill
  const color = congestion >= 70 ? '#ff2222'
              : congestion >= 50 ? '#ff8800'
              : congestion >= 30 ? '#ffdd00'
              : congestion >= 10 ? '#aadd00'
              : '#00cc44';

  const condition = congestion >= 70 ? 'GRIDLOCK'
                  : congestion >= 50 ? 'HEAVY'
                  : congestion >= 30 ? 'MODERATE'
                  : congestion >= 10 ? 'LIGHT'
                  : 'FREE FLOW';

  const closureRow = roadClosure
    ? `<span style="color:#ff4444">⚠ Road closure reported</span><br/>`
    : '';

  return `
    <div style="
      background:rgba(0,0,0,.92);border:1px solid ${color};
      padding:6px 10px;font:11px/1.6 'JetBrains Mono',monospace;
      color:#dddddd;border-radius:2px;pointer-events:none;min-width:180px;
    ">
      <b style="font-size:12px;color:${color};letter-spacing:.05em">${cityName}</b>${isDemo}<br/>
      <span style="
        background:${color};color:#000;
        padding:1px 6px;border-radius:2px;font-size:10px;font-weight:bold
      ">${condition}</span><br/>
      Speed: <b style="color:${color}">${speed.toFixed(0)} km/h</b>
      &nbsp; Free-flow: ${freeFlow.toFixed(0)} km/h<br/>
      Congestion: <b style="color:${color}">${congestion.toFixed(0)}%</b><br/>
      ${closureRow}
    </div>`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TrafficLayer() {
  const traffic         = useLayerData('traffic');
  const isVisible       = useGlobeStore((s) => s.layers.traffic);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);

  const setPoints = usePointMarkerStore((s) => s.setPoints);
  const setRings  = usePointMarkerStore((s) => s.setRings);

  // Listen for globe-point-click events dispatched by PointsLayerSync
  useEffect(() => {
    const handler = (e: Event) => {
      const pd = (e as CustomEvent<PointDatum>).detail;
      if (pd.layerKey === 'traffic') selectEvent(pd.ev.id);
    };
    window.addEventListener('globe-point-click', handler);
    return () => window.removeEventListener('globe-point-click', handler);
  }, [selectEvent]);

  // ── Point markers ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isVisible) {
      setPoints('traffic', []);
      return;
    }
    const data: PointDatum[] = traffic.map((ev) => ({
      ev,
      lat:      ev.latitude,
      lng:      ev.longitude,
      alt:      0.001,
      radius:   trafficRadius(ev, selectedEventId),
      color:    trafficColor(ev, selectedEventId),
      label:    buildLabel(ev),
      layerKey: 'traffic' as const,
    }));
    setPoints('traffic', data);
  }, [traffic, isVisible, selectedEventId, setPoints]);

  // ── Pulsing rings for gridlock cities + selected ──────────────────────────
  useEffect(() => {
    if (!isVisible) {
      setRings('traffic', []);
      return;
    }

    const highlighted = traffic.filter(
      (ev) => ev.severity >= 4 || ev.id === selectedEventId,
    );

    const rings: RingDatum[] = highlighted.map((ev) => {
      const meta       = ev.metadata as Record<string, unknown>;
      const c          = Number(meta?.congestion_percent ?? 0);
      const isSelected = ev.id === selectedEventId;
      const rgb        = c >= 70 ? '255,34,34'
                       : c >= 50 ? '255,136,0'
                       : '0,229,255';
      return {
        lat:       ev.latitude,
        lng:       ev.longitude,
        maxRadius: isSelected ? 5.0 : 2.5,
        color:     (t: number) => `rgba(${rgb},${Math.max(0, 0.85 - t * 1.1)})`,
        speed:     0.7,
        period:    2500,
        layerKey:  'traffic' as const,
      };
    });
    setRings('traffic', rings);
  }, [traffic, isVisible, selectedEventId, setRings]);

  return null;
}
