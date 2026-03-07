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

// ── Airplane icon factory ─────────────────────────────────────────────────

/**
 * Module-level CanvasTexture cache — created once, shared across all meshes.
 * Two variants: normal (neon yellow) and dim (on-ground aircraft).
 */
let _texNormal: THREE.CanvasTexture | null = null;
let _texDim:    THREE.CanvasTexture | null = null;

function buildAirplaneTexture(dim: boolean): THREE.CanvasTexture {
  const SIZE = 64;
  const canvas = document.createElement('canvas');
  canvas.width  = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.save();
  ctx.translate(SIZE / 2, SIZE / 2);

  const S = SIZE * 0.36; // shape scale
  ctx.fillStyle = dim ? '#886600' : '#ffee00';
  if (!dim) {
    ctx.shadowColor = '#ff9900';
    ctx.shadowBlur  = 8;
  }

  // Top-down airplane silhouette.
  // Nose points toward canvas top (local Y- in canvas = local +Y in Three.js
  // PlaneGeometry, which maps to the globe-surface North direction after lookAt).
  ctx.beginPath();
  ctx.moveTo(0,          -S);          // nose
  ctx.lineTo( S * 0.13,  -S * 0.15);   // right fuselage shoulder
  ctx.lineTo( S * 0.90,   S * 0.18);   // right wing tip
  ctx.lineTo( S * 0.52,   S * 0.42);   // right wing trailing edge
  ctx.lineTo( S * 0.16,   S * 0.28);   // right fuselage / tail root
  ctx.lineTo( S * 0.40,   S * 0.82);   // right horizontal stabiliser tip
  ctx.lineTo( S * 0.18,   S * 0.92);   // right stabiliser trailing corner
  ctx.lineTo(0,            S * 0.72);  // tail centre
  ctx.lineTo(-S * 0.18,   S * 0.92);   // left stabiliser trailing corner
  ctx.lineTo(-S * 0.40,   S * 0.82);   // left horizontal stabiliser tip
  ctx.lineTo(-S * 0.16,   S * 0.28);   // left fuselage / tail root
  ctx.lineTo(-S * 0.52,   S * 0.42);   // left wing trailing edge
  ctx.lineTo(-S * 0.90,   S * 0.18);   // left wing tip
  ctx.lineTo(-S * 0.13,  -S * 0.15);   // left fuselage shoulder
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  const tex = new THREE.CanvasTexture(canvas);
  if (dim) _texDim    = tex;
  else     _texNormal = tex;
  return tex;
}

function getAirplaneTexture(dim: boolean): THREE.CanvasTexture {
  if (dim) return _texDim    ?? buildAirplaneTexture(true);
  return         _texNormal  ?? buildAirplaneTexture(false);
}

/**
 * Flat PlaneGeometry mesh with a top-down airplane texture.
 * The plane lies in XY (face normal = +Z).
 * lookAt(0,0,0) makes +Z point away from the globe centre (outward),
 * so the icon is always visible from outside.
 */
function makeAirplane(dim: boolean): THREE.Mesh {
  const geo = new THREE.PlaneGeometry(0.9, 0.9);
  const mat = new THREE.MeshBasicMaterial({
    map:         getAirplaneTexture(dim),
    transparent: true,
    opacity:     dim ? 0.45 : 1.0,
    depthWrite:  false,
    side:        THREE.DoubleSide,
  });
  return new THREE.Mesh(geo, mat);
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
        const ev  = d as GlobeEvent;
        const dim = (ev.altitude ?? 999) < 50; // altitude in metres
        return makeAirplane(dim);
      })
      .customThreeObjectUpdate((obj: object, d: object) => {
        const ev   = d as GlobeEvent;
        const mesh = obj as THREE.Mesh;
        const mat  = mesh.material as THREE.MeshBasicMaterial;
        const dim  = (ev.altitude ?? 999) < 50;

        // ── Position on globe surface ─────────────────────────────────────
        // globe.getCoords(lat, lng, altFraction) → {x, y, z}
        const altFrac = Math.max(0, (ev.altitude ?? 0) / 6_371_000) + 0.002;
        const { x, y, z } = (globe as unknown as {
          getCoords: (lat: number, lng: number, alt: number) => { x: number; y: number; z: number };
        }).getCoords(ev.latitude, ev.longitude, altFrac);
        mesh.position.set(x, y, z);

        // ── Orient: face outward, rotate by heading ───────────────────────
        // lookAt(0,0,0) → local -Z points toward globe centre, +Z outward.
        // The PlaneGeometry face normal is +Z, so it faces the camera/outside.
        // Canvas top (nose) = Three.js local +Y ≈ North on the sphere surface.
        // rotateZ(-heading) turns the nose from North to the actual heading.
        mesh.lookAt(0, 0, 0);
        mesh.rotateZ((-(ev.heading ?? 0) * Math.PI) / 180);

        mat.opacity     = dim ? 0.45 : 1.0;
        mat.needsUpdate = true;
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

