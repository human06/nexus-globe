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
 *  - Selected aircraft: cyan (#00e5ff), 2× scale, pulsing ring, projection arc
 *  - Layer hides when flights toggle is off
 */
import { useEffect } from 'react';
import * as THREE from 'three';
import { useGlobe } from '../GlobeContext';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── Airplane icon factory ─────────────────────────────────────────────────

type TexVariant = 'normal' | 'dim' | 'selected';

const _texCache: Partial<Record<TexVariant, THREE.CanvasTexture>> = {};

function buildAirplaneTexture(variant: TexVariant): THREE.CanvasTexture {
  const SIZE = 64;
  const canvas = document.createElement('canvas');
  canvas.width  = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.save();
  ctx.translate(SIZE / 2, SIZE / 2);

  const S = SIZE * 0.36;

  if (variant === 'selected') {
    ctx.fillStyle   = '#ffffff';
    ctx.shadowColor = '#00e5ff';
    ctx.shadowBlur  = 16;
  } else if (variant === 'dim') {
    ctx.fillStyle = '#886600';
  } else {
    ctx.fillStyle   = '#ffee00';
    ctx.shadowColor = '#ff9900';
    ctx.shadowBlur  = 8;
  }

  // Top-down airplane silhouette (nose toward canvas top).
  ctx.beginPath();
  ctx.moveTo(0,          -S);
  ctx.lineTo( S * 0.13,  -S * 0.15);
  ctx.lineTo( S * 0.90,   S * 0.18);
  ctx.lineTo( S * 0.52,   S * 0.42);
  ctx.lineTo( S * 0.16,   S * 0.28);
  ctx.lineTo( S * 0.40,   S * 0.82);
  ctx.lineTo( S * 0.18,   S * 0.92);
  ctx.lineTo(0,            S * 0.72);
  ctx.lineTo(-S * 0.18,   S * 0.92);
  ctx.lineTo(-S * 0.40,   S * 0.82);
  ctx.lineTo(-S * 0.16,   S * 0.28);
  ctx.lineTo(-S * 0.52,   S * 0.42);
  ctx.lineTo(-S * 0.90,   S * 0.18);
  ctx.lineTo(-S * 0.13,  -S * 0.15);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  const tex = new THREE.CanvasTexture(canvas);
  _texCache[variant] = tex;
  return tex;
}

function getAirplaneTexture(variant: TexVariant): THREE.CanvasTexture {
  return _texCache[variant] ?? buildAirplaneTexture(variant);
}

function makeAirplane(variant: TexVariant): THREE.Mesh {
  const geo = new THREE.PlaneGeometry(0.9, 0.9);
  const mat = new THREE.MeshBasicMaterial({
    map:         getAirplaneTexture(variant),
    transparent: true,
    opacity:     variant === 'dim' ? 0.45 : 1.0,
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

// ── Geo projection utility ─────────────────────────────────────────────────

/** Returns [lat, lng] of a point distKm ahead from origin along headingDeg bearing */
function projectForward(
  lat: number, lng: number, headingDeg: number, distKm: number,
): [number, number] {
  const R    = 6371;
  const d    = distKm / R;
  const lat1 = (lat * Math.PI) / 180;
  const lng1 = (lng * Math.PI) / 180;
  const brng = (headingDeg * Math.PI) / 180;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng),
  );
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(brng) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
    );
  return [(lat2 * 180) / Math.PI, ((lng2 * 180) / Math.PI + 540) % 360 - 180];
}

// ── Component ──────────────────────────────────────────────────────────────

export default function FlightLayer() {
  const globe           = useGlobe();
  const flights         = useLayerData('flight');
  const isVisible       = useGlobeStore((s) => s.layers.flights);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);

  // ── Markers ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!globe) return;

    const data = isVisible ? flights : [];

    globe
      .customLayerData(data)
      .customThreeObject((d: object) => {
        const ev = d as GlobeEvent;
        const variant: TexVariant =
          ev.id === selectedEventId ? 'selected'
          : (ev.altitude ?? 999) < 50 ? 'dim'
          : 'normal';
        return makeAirplane(variant);
      })
      .customThreeObjectUpdate((obj: object, d: object) => {
        const ev         = d as GlobeEvent;
        const mesh       = obj as THREE.Mesh;
        const mat        = mesh.material as THREE.MeshBasicMaterial;
        const isSelected = ev.id === selectedEventId;
        const dim        = !isSelected && (ev.altitude ?? 999) < 50;
        const variant: TexVariant = isSelected ? 'selected' : dim ? 'dim' : 'normal';

        // ── Position ──────────────────────────────────────────────────────
        const altFrac = Math.max(0, (ev.altitude ?? 0) / 6_371_000) + 0.002;
        const { x, y, z } = (globe as unknown as {
          getCoords: (lat: number, lng: number, alt: number) => { x: number; y: number; z: number };
        }).getCoords(ev.latitude, ev.longitude, altFrac);
        mesh.position.set(x, y, z);

        // ── Orient: face outward, rotate by heading ───────────────────────
        mesh.lookAt(0, 0, 0);
        mesh.rotateZ((-(ev.heading ?? 0) * Math.PI) / 180);

        // ── Scale + texture swap ──────────────────────────────────────────
        mesh.scale.setScalar(isSelected ? 2.0 : 1.0);
        mat.map     = getAirplaneTexture(variant);
        mat.opacity = dim ? 0.45 : 1.0;
        mat.needsUpdate = true;
      })
      .customLayerLabel((d: object) => buildLabel(d as GlobeEvent))
      .onCustomLayerClick((d: object) => {
        selectEvent((d as GlobeEvent).id);
      });
  }, [globe, flights, isVisible, selectEvent, selectedEventId]);

  // ── Trails (pathsData) ───────────────────────────────────────────────────
  useEffect(() => {
    if (!globe) return;

    if (!isVisible) {
      globe.pathsData([]);
      return;
    }

    type TrailDatum = { pts: [number, number, number][]; selected: boolean };
    const trailData: TrailDatum[] = flights
      .filter((ev) => ev.trail && ev.trail.length >= 2)
      .map((ev) => ({
        pts: ev.trail!.map((p): [number, number, number] => [
          p.lat,
          p.lng,
          (p.alt ?? 0) / 1_000_000,
        ]),
        selected: ev.id === selectedEventId,
      }));

    globe
      .pathsData(trailData)
      .pathPoints('pts')
      .pathColor((d: object) => {
        const td = d as TrailDatum;
        return td.selected
          ? ['rgba(0,229,255,1)', 'rgba(0,229,255,0.25)']
          : ['rgba(255,238,0,0.9)', 'rgba(255,238,0,0)'];
      })
      .pathStroke((d: object) => ((d as TrailDatum).selected ? 0.9 : 0.3))
      .pathDashLength(0.01)
      .pathDashGap(0)
      .pathDashAnimateTime(0);
  }, [globe, flights, isVisible, selectedEventId]);

  // ── Pulsing ring + projection arc for selected flight ────────────────────
  useEffect(() => {
    if (!globe) return;

    const sel = selectedEventId
      ? flights.find((ev) => ev.id === selectedEventId) ?? null
      : null;

    // Pulsing ring around selected aircraft
    globe
      .ringsData(sel ? [sel] : [])
      .ringLat((d: object) => (d as GlobeEvent).latitude)
      .ringLng((d: object) => (d as GlobeEvent).longitude)
      .ringMaxRadius(3.5)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .ringColor((() => (t: number) => `rgba(0,229,255,${Math.max(0, 1 - t * 1.4)})`) as any)
      .ringPropagationSpeed(1.5)
      .ringRepeatPeriod(900);

    // Dashed projection arc: current position → 2-hour forward look
    if (sel && sel.heading != null && sel.speed != null && sel.speed > 20) {
      // speed is stored as km/h (normalised in flightradar.py)
      const distKm = sel.speed * 2; // 2-hour projection
      const [endLat, endLng] = projectForward(
        sel.latitude, sel.longitude, sel.heading, distKm,
      );
      globe
        .arcsData([sel])
        .arcStartLat((d: object) => (d as GlobeEvent).latitude)
        .arcStartLng((d: object) => (d as GlobeEvent).longitude)
        .arcEndLat(() => endLat)
        .arcEndLng(() => endLng)
        .arcAltitudeAutoScale(0.3)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .arcColor((() => ['rgba(0,229,255,0.15)', 'rgba(0,229,255,0.85)']) as any)
        .arcStroke(0.5)
        .arcDashLength(0.35)
        .arcDashGap(0.15)
        .arcDashAnimateTime(1800);
    } else {
      globe.arcsData([]);
    }
  }, [globe, flights, selectedEventId]);

  return null;
}

