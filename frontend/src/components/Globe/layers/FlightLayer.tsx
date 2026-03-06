/**
 * FlightLayer — renders live ADS-B flight data on the Globe.GL instance.
 *
 * Uses Globe.GL's custom Three.js layer for markers and pathsData for trails.
 * Purely imperative (no DOM) — returns null from render.
 *
 * Acceptance criteria:
 *  - Neon-yellow (#ffee00) arrowhead markers pointing in heading direction
 *  - Fading trail showing last N positions
 *  - HTML tooltip on hover: callsign, altitude (ft), speed (kts)
 *  - Click → selectEvent() in Zustand store
 *  - On-ground aircraft: dimmed (35 % opacity)
 *  - Layer hides when flights toggle is off
 */
import { useEffect } from 'react';
import * as THREE from 'three';
import { useGlobe } from '../GlobeContext';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── Arrow geometry factory ─────────────────────────────────────────────────

/**
 * A thin 4-sided cone (diamond arrow) oriented so its tip points +X (East).
 * Globe.GL applies local-space rotations to match heading on the sphere.
 */
function makeArrow(dim: boolean): THREE.Mesh {
  const g = new THREE.ConeGeometry(0.25, 0.7, 4);
  // Rotate tip to point in +Z (forward) in local space; globe.gl will
  // rotate it onto the sphere surface.
  g.rotateX(Math.PI / 2);
  const m = new THREE.MeshLambertMaterial({
    color:              dim ? 0x886600 : 0xffee00,
    emissive:           dim ? 0x221100 : 0xff9900,
    emissiveIntensity:  dim ? 0.05 : 0.5,
    transparent:        true,
    opacity:            dim ? 0.35 : 0.95,
  });
  return new THREE.Mesh(g, m);
}

// ── Tooltip template ───────────────────────────────────────────────────────

function buildLabel(ev: GlobeEvent): string {
  const meta = ev.metadata as Record<string, unknown>;
  const cs    = String(meta?.callsign    ?? ev.title ?? '').trim() || '—';
  const cntry = String(meta?.origin_country ?? meta?.country ?? '').trim() || '—';
  const icao  = String(meta?.icao24      ?? '').toUpperCase() || '—';
  const altFt = ev.altitude != null ? `${Math.round(ev.altitude * 3.28084).toLocaleString()} ft` : '—';
  const spdKt = ev.speed    != null ? `${Math.round(ev.speed * 0.539957)} kts` : '—';
  const hdg   = ev.heading  != null ? `${Math.round(ev.heading)}°` : '—';
  return `
    <div style="
      background:rgba(0,0,0,.92);border:1px solid #ffee00;
      padding:6px 10px;font:11px/1.6 'JetBrains Mono',monospace;
      color:#ffee00;border-radius:2px;pointer-events:none;
    ">
      <b style="font-size:13px;letter-spacing:.05em">${cs}</b><br/>
      Alt: ${altFt} &nbsp; Spd: ${spdKt} &nbsp; Hdg: ${hdg}<br/>
      <span style="color:rgba(255,238,0,.6)">${cntry} · ${icao}</span>
    </div>`;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function FlightLayer() {
  const globe     = useGlobe();
  const flights   = useLayerData('flight');
  const isVisible = useGlobeStore((s) => s.layers.flights);
  const selectEvent = useGlobeStore((s) => s.selectEvent);

  // ── Markers ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!globe) return;

    const data = isVisible ? flights : [];

    globe
      .customLayerData(data)
      .customThreeObject((d: object) => {
        const ev = d as GlobeEvent;
        return makeArrow((ev.altitude ?? 999) < 50);
      })
      .customThreeObjectUpdate((obj: object, d: object) => {
        const ev   = d as GlobeEvent;
        const mesh = obj as THREE.Mesh;
        const mat  = mesh.material as THREE.MeshLambertMaterial;
        const dim  = (ev.altitude ?? 999) < 50;
        // Rotate arrowhead to heading direction (local Z → heading angle)
        mesh.rotation.y = (-(ev.heading ?? 0) * Math.PI) / 180;
        mat.opacity            = dim ? 0.35 : 0.95;
        mat.emissiveIntensity  = dim ? 0.05 : 0.5;
        mat.needsUpdate        = true;
      })
      .customLayerLabel((d: object) => buildLabel(d as GlobeEvent))
      .onCustomLayerClick((d: object) => {
        selectEvent((d as GlobeEvent).id);
      });
  }, [globe, flights, isVisible, selectEvent]);

  // ── Trails (pathsData) ───────────────────────────────────────────────────
  useEffect(() => {
    if (!globe) return;

    if (!isVisible) {
      globe.pathsData([]);
      return;
    }

    type TrailDatum = { pts: [number, number, number][] };
    const trailData: TrailDatum[] = flights
      .filter((ev) => ev.trail && ev.trail.length >= 2)
      .map((ev) => ({
        pts: ev.trail!.map((p): [number, number, number] => [
          p.lat,
          p.lng,
          // Normalise altitude to globe unit scale (rough: 1 km → 0.0001)
          ((p.alt ?? 0) / 1_000_000),
        ]),
      }));

    globe
      .pathsData(trailData)
      .pathPoints('pts')
      // Array of two colours → gradient from head (bright) to tail (transparent)
      .pathColor(() => ['rgba(255,238,0,0.9)', 'rgba(255,238,0,0)'])
      .pathStroke(0.3)
      .pathDashLength(0.01)
      .pathDashGap(0)
      .pathDashAnimateTime(0);
  }, [globe, flights, isVisible]);

  return null;
}

