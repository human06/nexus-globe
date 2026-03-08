/**
 * SatelliteLayer — renders live satellite positions as 3D sprites directly
 * injected into Globe.GL's Three.js scene (globe.scene()).
 *
 * Why scene injection instead of globe.customLayerData():
 *  FlightLayer already owns the single customLayerData slot in Globe.GL.
 *  By adding objects directly to the scene we avoid that conflict and gain
 *  full freedom over depth, scale, and type of objects.
 *
 * Visuals:
 *  - Canvas-drawn satellite icon (body + solar panels) per category/state
 *  - THREE.Sprite so it always faces the camera — appears as a flat icon
 *  - Positioned using globe.getCoords() at the satellite's real altitude
 *  - Zooming in past a satellite still shows it hovering at altitude
 *  - Selected satellite: cyan, larger, full orbital path as THREE.Line, ring
 *  - Tooltip follows the mouse cursor on hover
 *  - Layer hides entirely when satellites toggle is off
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { useGlobe } from '../GlobeContext';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import { usePointMarkerStore } from '../pointMarkerStore';
import type { RingDatum } from '../pointMarkerStore';
import type { GlobeEvent } from '../../../types/events';

// ── Globe.GL internal API we rely on ─────────────────────────────────────────

type GlobeEx = {
  scene:     () => THREE.Scene;
  camera:    () => THREE.Camera;
  renderer:  () => THREE.WebGLRenderer;
  getCoords: (lat: number, lng: number, alt: number) => { x: number; y: number; z: number };
};

// ── Satellite icon texture factory ────────────────────────────────────────────

type SatVariant = 'normal' | 'station' | 'starlink' | 'military' | 'weather' | 'gps' | 'resource' | 'amateur' | 'selected';

const _texCache = new Map<SatVariant, THREE.CanvasTexture>();

const COLORS: Record<SatVariant, { body: string; glow: string; panel: string }> = {
  normal:   { body: '#ff00aa', glow: 'rgba(255,0,170,0.55)',   panel: '#cc0088' },
  station:  { body: '#e8f4ff', glow: 'rgba(200,230,255,0.75)', panel: '#aad0ff' },
  starlink: { body: '#cc66ff', glow: 'rgba(200,100,255,0.55)', panel: '#8833cc' },
  military: { body: '#ff3333', glow: 'rgba(255,50,50,0.55)',   panel: '#cc0000' },
  weather:  { body: '#44bbff', glow: 'rgba(68,187,255,0.55)',  panel: '#2288cc' },
  gps:      { body: '#ffee44', glow: 'rgba(255,238,68,0.55)',  panel: '#ccbb00' },
  resource: { body: '#44ffaa', glow: 'rgba(68,255,170,0.55)',  panel: '#22cc88' },
  amateur:  { body: '#ff9944', glow: 'rgba(255,153,68,0.55)',  panel: '#cc6600' },
  selected: { body: '#00e5ff', glow: 'rgba(0,229,255,0.9)',    panel: '#0099bb' },
};

function buildSatTexture(variant: SatVariant): THREE.CanvasTexture {
  const S = 80;
  const c = document.createElement('canvas');
  c.width = S; c.height = S;
  const ctx = c.getContext('2d')!;
  ctx.clearRect(0, 0, S, S);

  const { body, glow, panel } = COLORS[variant];
  const cx = S / 2, cy = S / 2;

  // Soft radial glow halo
  const g = ctx.createRadialGradient(cx, cy, 2, cx, cy, S * 0.44);
  g.addColorStop(0,   glow);
  g.addColorStop(0.4, glow.replace(/[\d.]+\)$/, '0.12)'));
  g.addColorStop(1,   'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, S, S);

  // Solar panel arrays — left and right (2 cells each)
  const panW = S * 0.28, panH = S * 0.09;
  const panY = cy - panH / 2;
  const gap  = S * 0.10;
  ctx.shadowColor = body;
  ctx.shadowBlur  = 5;
  ctx.fillStyle   = panel;
  ctx.fillRect(cx - gap - panW * 2,     panY, panW, panH); // left outer
  ctx.fillRect(cx - gap - panW - 1,     panY, panW, panH); // left inner
  ctx.fillRect(cx + gap,                panY, panW, panH); // right inner
  ctx.fillRect(cx + gap + panW + 1,     panY, panW, panH); // right outer

  // Thin struts
  ctx.fillStyle = panel;
  ctx.shadowBlur = 0;
  ctx.fillRect(cx - gap - 1, cy - 1, gap + 1, 2); // left strut
  ctx.fillRect(cx,            cy - 1, gap,     2); // right strut

  // Body — small square
  const bw = S * 0.20;
  ctx.shadowColor = body;
  ctx.shadowBlur  = variant === 'selected' ? 18 : 10;
  ctx.fillStyle   = variant === 'selected' ? '#001820' : '#080810';
  ctx.fillRect(cx - bw / 2, cy - bw / 2, bw, bw);
  ctx.strokeStyle = body;
  ctx.lineWidth   = variant === 'selected' ? 2.5 : 1.5;
  ctx.strokeRect(cx - bw / 2, cy - bw / 2, bw, bw);

  // Antenna stub at top of body
  ctx.beginPath();
  ctx.moveTo(cx, cy - bw / 2);
  ctx.lineTo(cx, cy - bw / 2 - S * 0.10);
  ctx.strokeStyle = body;
  ctx.lineWidth   = 1.2;
  ctx.shadowBlur  = 4;
  ctx.stroke();
  // Antenna tip dot
  ctx.beginPath();
  ctx.arc(cx, cy - bw / 2 - S * 0.10, S * 0.025, 0, Math.PI * 2);
  ctx.fillStyle  = body;
  ctx.shadowBlur = 6;
  ctx.fill();

  // Centre body dot
  ctx.beginPath();
  ctx.arc(cx, cy, S * 0.03, 0, Math.PI * 2);
  ctx.fillStyle  = '#ffffff';
  ctx.shadowBlur = 4;
  ctx.fill();

  const tex = new THREE.CanvasTexture(c);
  _texCache.set(variant, tex);
  return tex;
}

function getSatTex(v: SatVariant): THREE.CanvasTexture {
  return _texCache.get(v) ?? buildSatTexture(v);
}

function satVariant(ev: GlobeEvent, selId: string | null): SatVariant {
  if (ev.id === selId) return 'selected';
  const cat = (ev.category ?? '').toLowerCase();
  if (cat === 'stations' || cat === 'station') return 'station';
  if (cat === 'starlink') return 'starlink';
  if (cat.includes('military')) return 'military';
  if (cat.includes('weather')) return 'weather';
  if (cat.includes('gps') || cat.includes('navigation') || cat === 'gps-ops') return 'gps';
  if (cat.includes('resource') || cat.includes('earth-obs')) return 'resource';
  if (cat === 'amateur') return 'amateur';
  return 'normal';
}

/** Sprite world-space scale — globe radius ≈ 100 Three.js world units */
function satScale(ev: GlobeEvent, selId: string | null): number {
  if (ev.id === selId) return 4.5;
  const cat = (ev.category ?? '').toLowerCase();
  if (cat === 'stations' || cat === 'station') return 3.5;
  if (cat === 'starlink') return 1.4;
  return 2.2;
}

// ── Tooltip HTML ──────────────────────────────────────────────────────────────

function buildTip(ev: GlobeEvent): string {
  const meta   = ev.metadata as Record<string, unknown>;
  const norad  = String(meta?.norad_id  ?? '—');
  const alt    = ev.altitude != null ? `${Math.round(ev.altitude / 1000)} km` : '—';
  const speed  = ev.speed    != null ? `${Math.round(ev.speed)} km/h` : '—';
  const inc    = meta?.inclination_deg != null ? `${Number(meta.inclination_deg).toFixed(1)}°` : '—';
  const period = meta?.period_min      != null ? `${Number(meta.period_min).toFixed(1)} min` : '—';
  const group  = String(meta?.group ?? ev.category ?? '—');
  return [
    `<b style="color:#ff00aa;font-size:12px">${ev.title}</b>`,
    `Alt: ${alt} &nbsp; Spd: ${speed}`,
    `Period: ${period} &nbsp; Inc: ${inc}`,
    `<span style="color:rgba(255,0,170,.5)">NORAD ${norad} · ${group}</span>`,
  ].join('<br/>');
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SatelliteLayer() {
  const globe           = useGlobe() as unknown as (GlobeEx & object) | null;
  const satellites      = useLayerData('satellite');
  const isVisible       = useGlobeStore((s) => s.layers.satellites);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);
  const setRings        = usePointMarkerStore((s) => s.setRings);

  // Clear any residual point/arc data written by the previous implementation
  const setPoints = usePointMarkerStore((s) => s.setPoints);
  const setArcs   = usePointMarkerStore((s) => s.setArcs);
  useEffect(() => {
    setPoints('satellite', []);
    setArcs('satellite', []);
  }, [setPoints, setArcs]);

  // Tooltip state
  const [tooltip, setTooltip] = useState<{ html: string; x: number; y: number } | null>(null);

  // Stable refs to Three.js objects
  const groupRef     = useRef<THREE.Group | null>(null);
  const orbitLineRef = useRef<THREE.Line | null>(null);
  const spriteMapRef = useRef<Map<string, THREE.Sprite>>(new Map());
  const evMapRef     = useRef<Map<string, GlobeEvent>>(new Map());
  const rcRef        = useRef(new THREE.Raycaster());

  // ── Mount: inject Group into globe.scene() ────────────────────────────────
  useEffect(() => {
    if (!globe) return;
    const g = globe as unknown as GlobeEx;
    const scene = g.scene();
    const group = new THREE.Group();
    group.name = 'SatelliteLayer';
    scene.add(group);
    groupRef.current = group;

    return () => {
      scene.remove(group);
      for (const s of spriteMapRef.current.values()) {
        (s.material as THREE.SpriteMaterial).dispose();
      }
      spriteMapRef.current.clear();
      evMapRef.current.clear();
      group.clear();
      if (orbitLineRef.current) {
        scene.remove(orbitLineRef.current);
        (orbitLineRef.current.material as THREE.Material).dispose();
        orbitLineRef.current.geometry.dispose();
        orbitLineRef.current = null;
      }
    };
  }, [globe]);

  // ── Click: raycast against sprites ───────────────────────────────────────
  useEffect(() => {
    if (!globe) return;
    const g      = globe as unknown as GlobeEx;
    const canvas = g.renderer().domElement;

    const onClick = (e: MouseEvent) => {
      const group = groupRef.current;
      if (!group || !group.visible) return;
      const rect = canvas.getBoundingClientRect();
      const ndx  = ((e.clientX - rect.left) / rect.width)  * 2 - 1;
      const ndy  = ((e.clientY - rect.top)  / rect.height) * -2 + 1;
      rcRef.current.setFromCamera(new THREE.Vector2(ndx, ndy), g.camera());
      const hits = rcRef.current.intersectObjects(group.children, false);
      if (hits.length > 0) {
        const evId = (hits[0].object as THREE.Sprite).userData.evId as string;
        if (evId) { selectEvent(evId); }
      }
    };

    canvas.addEventListener('click', onClick);
    return () => canvas.removeEventListener('click', onClick);
  }, [globe, selectEvent]);

  // ── Hover: tooltip via raycasting ────────────────────────────────────────
  useEffect(() => {
    if (!globe) return;
    const g      = globe as unknown as GlobeEx;
    const canvas = g.renderer().domElement;

    const onMove = (e: MouseEvent) => {
      const group = groupRef.current;
      if (!group || !group.visible) { setTooltip(null); return; }
      const rect = canvas.getBoundingClientRect();
      const ndx  = ((e.clientX - rect.left) / rect.width)  * 2 - 1;
      const ndy  = ((e.clientY - rect.top)  / rect.height) * -2 + 1;
      rcRef.current.setFromCamera(new THREE.Vector2(ndx, ndy), g.camera());
      const hits = rcRef.current.intersectObjects(group.children, false);
      if (hits.length > 0) {
        const evId = (hits[0].object as THREE.Sprite).userData.evId as string;
        const ev   = evId ? evMapRef.current.get(evId) : undefined;
        if (ev) {
          setTooltip({ html: buildTip(ev), x: e.clientX, y: e.clientY });
          canvas.style.cursor = 'pointer';
          return;
        }
      }
      setTooltip(null);
      canvas.style.cursor = '';
    };

    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('mouseleave', () => setTooltip(null));
    return () => {
      canvas.removeEventListener('mousemove', onMove);
      setTooltip(null);
    };
  }, [globe]);

  // ── Update sprites on data change ────────────────────────────────────────
  useEffect(() => {
    const group = groupRef.current;
    if (!group || !globe) return;

    if (!isVisible) { group.visible = false; return; }
    group.visible = true;

    const g       = globe as unknown as GlobeEx;
    const liveIds = new Set<string>();

    for (const ev of satellites) {
      liveIds.add(ev.id);
      evMapRef.current.set(ev.id, ev);

      const altFrac = Math.max(0.002, (ev.altitude ?? 400_000) / 6_371_000);
      const { x, y, z } = g.getCoords(ev.latitude, ev.longitude, altFrac);
      const variant = satVariant(ev, selectedEventId);
      const scale   = satScale(ev, selectedEventId);

      let sprite = spriteMapRef.current.get(ev.id);
      if (!sprite) {
        const mat = new THREE.SpriteMaterial({
          map:             getSatTex(variant),
          transparent:     true,
          depthWrite:      false,
          sizeAttenuation: true,
        });
        sprite = new THREE.Sprite(mat);
        sprite.userData.evId = ev.id;
        group.add(sprite);
        spriteMapRef.current.set(ev.id, sprite);
      } else {
        const mat    = sprite.material as THREE.SpriteMaterial;
        const newTex = getSatTex(variant);
        if (mat.map !== newTex) { mat.map = newTex; mat.needsUpdate = true; }
      }

      sprite.position.set(x, y, z);
      sprite.scale.setScalar(scale);
    }

    // Prune stale sprites
    for (const [id, sprite] of spriteMapRef.current) {
      if (!liveIds.has(id)) {
        group.remove(sprite);
        (sprite.material as THREE.SpriteMaterial).dispose();
        spriteMapRef.current.delete(id);
        evMapRef.current.delete(id);
      }
    }
  }, [globe, satellites, isVisible, selectedEventId]);

  // ── Orbital path for selected satellite ──────────────────────────────────
  useEffect(() => {
    if (!globe) return;
    const g     = globe as unknown as GlobeEx;
    const scene = g.scene();

    // Remove previous orbit line
    if (orbitLineRef.current) {
      scene.remove(orbitLineRef.current);
      (orbitLineRef.current.material as THREE.Material).dispose();
      orbitLineRef.current.geometry.dispose();
      orbitLineRef.current = null;
    }

    if (!isVisible || !selectedEventId) return;
    const sel = satellites.find((ev) => ev.id === selectedEventId);
    if (!sel || !sel.trail || sel.trail.length < 2) return;

    const satAlt = Math.max(0.002, (sel.altitude ?? 400_000) / 6_371_000);

    const pts: THREE.Vector3[] = sel.trail.map(({ lat, lng, alt: tAlt }) => {
      const a = tAlt != null ? Math.max(0.002, tAlt / 6_371_000) : satAlt;
      const { x, y, z } = g.getCoords(lat, lng, a);
      return new THREE.Vector3(x, y, z);
    });
    pts.push(pts[0].clone()); // close loop

    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({
      color:       0x00e5ff,
      opacity:     0.75,
      transparent: true,
      depthWrite:  false,
    });
    const line = new THREE.Line(geo, mat);
    line.name = 'SatOrbit';
    scene.add(line);
    orbitLineRef.current = line;
  }, [globe, satellites, isVisible, selectedEventId]);

  // ── Pulsing ring on the globe surface ─────────────────────────────────────
  const clearRings = useCallback(() => setRings('satellite', []), [setRings]);

  useEffect(() => {
    const sel = selectedEventId
      ? satellites.find((ev) => ev.id === selectedEventId) ?? null
      : null;
    if (!sel || !isVisible) { clearRings(); return; }
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
  }, [satellites, isVisible, selectedEventId, setRings, clearRings]);

  useEffect(() => () => clearRings(), [clearRings]);

  // ── Tooltip overlay ───────────────────────────────────────────────────────
  if (!tooltip) return null;
  const { html, x, y } = tooltip;
  const flipUp = y > window.innerHeight * 0.68;

  return (
    <div
      style={{
        position:      'fixed',
        left:          x + 14,
        top:           flipUp ? y - 10 : y + 10,
        transform:     flipUp ? 'translateY(-100%)' : 'none',
        zIndex:        50,
        background:    'rgba(0,0,0,0.92)',
        border:        '1px solid #ff00aa',
        padding:       '6px 10px',
        fontFamily:    "'JetBrains Mono', monospace",
        fontSize:      '11px',
        lineHeight:    1.6,
        color:         '#ff88dd',
        borderRadius:  2,
        pointerEvents: 'none',
        minWidth:      180,
        boxShadow:     '0 0 14px rgba(255,0,170,0.3)',
        whiteSpace:    'nowrap',
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

