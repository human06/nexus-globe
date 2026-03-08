/**
 * ShipLayer — renders AIS ship positions as WebGL Three.js sprites injected
 * directly into Globe.GL's Three.js scene (globe.scene()).
 *
 * Why WebGL instead of HTML DOM markers:
 *  The previous DOM approach was capped at ~300 ships due to browser layout
 *  cost per HTML element.  By using THREE.Sprites we render 5 000+ ships at
 *  60 fps with zero DOM overhead — geometry lives entirely on the GPU.
 *
 * Visuals:
 *  - Neon-green upward-arrow sprite per ship
 *  - sprite.material.rotation  = heading_deg → arrow points in vessel direction
 *  - Dimmed opacity for vessels at anchor (speed < 0.5 kts)
 *  - Category colour: cargo=green / tanker=orange / passenger=blue /
 *                     fishing=yellow / military=red / other=cyan
 *  - Selected: brighter, larger sprite
 *  - Hover: CSS tooltip panel positioned at mouse
 *  - Layer hides when ships toggle is off
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { useGlobe } from '../GlobeContext';
import { useHtmlMarkersStore } from '../htmlMarkersStore';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── Globe.GL internal surface ─────────────────────────────────────────────────

type GlobeEx = {
  scene:     () => THREE.Scene;
  camera:    () => THREE.Camera;
  renderer:  () => THREE.WebGLRenderer;
  getCoords: (lat: number, lng: number, alt: number) => { x: number; y: number; z: number };
};

// ── Category → colour ─────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  cargo:     '#00ff88',
  tanker:    '#ff9944',
  passenger: '#44aaff',
  fishing:   '#ffee44',
  military:  '#ff3333',
  tug:       '#ff66cc',
  pleasure:  '#cc88ff',
  sailing:   '#88ffee',
};

function shipColor(ev: GlobeEvent): string {
  const cat = (ev.category ?? '').toLowerCase();
  for (const [key, col] of Object.entries(CATEGORY_COLORS)) {
    if (cat.includes(key)) return col;
  }
  return '#00ccff';
}

// ── Canvas texture factory ────────────────────────────────────────────────────

const _texCache = new Map<string, THREE.CanvasTexture>();

function buildShipTexture(hexColor: string, selected = false): THREE.CanvasTexture {
  const cacheKey = `${hexColor}:${selected}`;
  if (_texCache.has(cacheKey)) return _texCache.get(cacheKey)!;
  const S = 64;
  const c = document.createElement('canvas');
  c.width = S; c.height = S;
  const ctx = c.getContext('2d')!;
  const cx = S / 2, cy = S / 2;

  const rg = ctx.createRadialGradient(cx, cy, 2, cx, cy, S * 0.42);
  rg.addColorStop(0,   hexColor + '88');
  rg.addColorStop(0.5, hexColor + '22');
  rg.addColorStop(1,   'rgba(0,0,0,0)');
  ctx.fillStyle = rg;
  ctx.fillRect(0, 0, S, S);

  ctx.shadowColor = hexColor;
  ctx.shadowBlur  = selected ? 10 : 5;
  ctx.fillStyle   = selected ? '#ffffff' : hexColor;
  ctx.strokeStyle = selected ? '#ffffff' : hexColor;
  ctx.lineWidth   = 1.2;

  ctx.beginPath();
  ctx.moveTo(cx,             cy - S * 0.35);
  ctx.lineTo(cx + S * 0.13,  cy + S * 0.10);
  ctx.lineTo(cx + S * 0.06,  cy + S * 0.20);
  ctx.lineTo(cx,             cy + S * 0.12);
  ctx.lineTo(cx - S * 0.06,  cy + S * 0.20);
  ctx.lineTo(cx - S * 0.13,  cy + S * 0.10);
  ctx.closePath();
  ctx.globalAlpha = selected ? 1.0 : 0.9;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.stroke();

  const tex = new THREE.CanvasTexture(c);
  _texCache.set(cacheKey, tex);
  return tex;
}

function buildAnchorTexture(): THREE.CanvasTexture {
  return buildShipTexture('#445544', false);
}

// ── LOD scale ─────────────────────────────────────────────────────────────────

function shipScale(alt: number): number {
  if (alt > 3.0) return 1.5;
  if (alt > 2.0) return 1.8;
  if (alt > 1.0) return 2.2;
  return 2.8;
}

// ── Tooltip state ─────────────────────────────────────────────────────────────

interface TooltipState { x: number; y: number; ev: GlobeEvent; }

// ── Component ─────────────────────────────────────────────────────────────────

export default function ShipLayer() {
  const globe      = useGlobe() as unknown as GlobeEx | null;
  const globeRef   = useRef(globe);
  globeRef.current = globe;

  const isVisible   = useGlobeStore((s) => s.layers.ships);
  const selectedId  = useGlobeStore((s) => s.selectedEventId);
  const selectEvent = useGlobeStore((s) => s.selectEvent);
  const cameraAlt   = useGlobeStore((s) => s.cameraAltitude);
  const setLayer    = useHtmlMarkersStore((s) => s.setLayer);

  // Dynamic render cap based on zoom level
  const renderCap = cameraAlt > 3.0 ? 800 : cameraAlt > 2.0 ? 2000 : 5000;
  const ships     = useLayerData('ship', renderCap);

  const spritesRef = useRef<THREE.Sprite[]>([]);
  const evMapRef   = useRef<Map<THREE.Sprite, GlobeEvent>>(new Map());
  const groupRef   = useRef<THREE.Group | null>(null);

  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const mouseRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const rafRef   = useRef<number>(0);

  // Clear HTML ship slot (we no longer use htmlMarkersStore for ships)
  useEffect(() => { setLayer('ship', []); return () => { setLayer('ship', []); }; }, [setLayer]);

  // ── Build / rebuild sprites when data changes ───────────────────────────────
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const scene = g.scene();

    if (groupRef.current) {
      scene.remove(groupRef.current);
      spritesRef.current.forEach((s) => s.material.dispose());
      spritesRef.current = [];
      evMapRef.current.clear();
    }

    if (!isVisible || ships.length === 0) { groupRef.current = null; return; }

    const group = new THREE.Group();
    group.name  = 'nexus-ship-layer';
    const sprites: THREE.Sprite[]              = [];
    const evMap   = new Map<THREE.Sprite, GlobeEvent>();

    for (const ev of ships) {
      const lat = ev.latitude;
      const lng = ev.longitude;
      if (lat == null || lng == null) continue;

      const meta     = (ev.metadata ?? {}) as Record<string, unknown>;
      const speedKts = (meta.sog_kts ?? meta.speed ?? ev.speed ?? 1) as number;
      const heading  = (meta.heading ?? ev.heading ?? 0) as number;
      const isAnchor = speedKts < 0.5;
      const isSel    = ev.id === selectedId;

      const tex = isAnchor
        ? buildAnchorTexture()
        : buildShipTexture(shipColor(ev), isSel);

      const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true,
        opacity:         isAnchor ? 0.40 : isSel ? 1.0 : 0.82,
        depthWrite:      false,
        sizeAttenuation: true,
      });
      mat.rotation = (heading * Math.PI) / 180;

      const sprite = new THREE.Sprite(mat);
      const sc     = shipScale(cameraAlt) * (isSel ? 1.7 : 1.0);
      sprite.scale.setScalar(sc);

      const cc = g.getCoords(lat, lng, 0);
      sprite.position.set(cc.x, cc.y, cc.z);

      group.add(sprite);
      sprites.push(sprite);
      evMap.set(sprite, ev);
    }

    scene.add(group);
    groupRef.current  = group;
    spritesRef.current = sprites;
    evMapRef.current  = evMap;

    return () => {
      scene.remove(group);
      sprites.forEach((s) => s.material.dispose());
    };
  }, [ships, isVisible, selectedId, cameraAlt]);

  // ── Raycaster hover ─────────────────────────────────────────────────────────
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const canvas = g.renderer().domElement;

    const onMove = (e: MouseEvent) => { mouseRef.current = { x: e.clientX, y: e.clientY }; };
    canvas.addEventListener('mousemove', onMove, { passive: true });

    const rc = new THREE.Raycaster();
    rc.params.Sprite = { threshold: 0.04 };

    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const g2      = globeRef.current;
      const sprites = spritesRef.current;
      if (!g2 || !sprites.length) return;

      const rect = canvas.getBoundingClientRect();
      const ndcX = ((mouseRef.current.x - rect.left) / rect.width)  * 2 - 1;
      const ndcY = -((mouseRef.current.y - rect.top)  / rect.height) * 2 + 1;
      rc.setFromCamera(new THREE.Vector2(ndcX, ndcY), g2.camera());

      const hits = rc.intersectObjects(sprites);
      if (hits.length) {
        const ev = evMapRef.current.get(hits[0].object as THREE.Sprite);
        if (ev) { setTooltip({ x: mouseRef.current.x, y: mouseRef.current.y, ev }); canvas.style.cursor = 'pointer'; return; }
      }
      setTooltip(null);
      canvas.style.cursor = '';
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      canvas.removeEventListener('mousemove', onMove);
    };
  }, []);

  // ── Click ────────────────────────────────────────────────────────────────────
  const handleClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const g = globeRef.current;
    if (!g || !spritesRef.current.length) return;
    const canvas = g.renderer().domElement;
    const rect   = canvas.getBoundingClientRect();
    const ndcX   = ((e.clientX - rect.left) / rect.width)  * 2 - 1;
    const ndcY   = -((e.clientY - rect.top)  / rect.height) * 2 + 1;
    const rc     = new THREE.Raycaster();
    rc.params.Sprite = { threshold: 0.04 };
    rc.setFromCamera(new THREE.Vector2(ndcX, ndcY), g.camera());
    const hits = rc.intersectObjects(spritesRef.current);
    if (hits.length) {
      const ev = evMapRef.current.get(hits[0].object as THREE.Sprite);
      if (ev) selectEvent(ev.id);
    }
  }, [selectEvent]);

  // ── Tooltip ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 5 }}
         onClick={handleClick as unknown as React.MouseEventHandler}>
      {tooltip && (() => {
        const ev   = tooltip.ev;
        const meta = (ev.metadata ?? {}) as Record<string, unknown>;
        const col  = shipColor(ev);
        const spd  = (meta.sog_kts ?? meta.speed ?? ev.speed) as number | undefined;
        const hdg  = (meta.heading ?? ev.heading) as number | undefined;
        return (
          <div style={{
            position: 'fixed', left: tooltip.x + 14, top: tooltip.y - 10,
            background: 'rgba(0,0,0,0.9)', border: `1px solid ${col}66`,
            padding: '7px 11px', fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10.5px', lineHeight: '1.6', color: '#d0ffd8',
            borderRadius: 3, pointerEvents: 'none', zIndex: 9999,
            minWidth: 160, maxWidth: 240, boxShadow: '0 2px 16px rgba(0,0,0,0.7)',
          }}>
            <div style={{ color: col, fontWeight: 700, marginBottom: 3 }}>
              {ev.title.split('—')[0].trim()}
            </div>
            {!!meta.vessel_type  && <div style={{ opacity: 0.7 }}>Type: {meta.vessel_type as string}</div>}
            {spd  != null        && <div style={{ opacity: 0.7 }}>Speed: {Number(spd).toFixed(1)} kts</div>}
            {hdg  != null        && <div style={{ opacity: 0.7 }}>HDG: {Number(hdg).toFixed(0)}°</div>}
            {!!meta.flag         && <div style={{ opacity: 0.7 }}>Flag: {meta.flag as string}</div>}
            {!!meta.destination  && <div style={{ opacity: 0.6 }}>→ {meta.destination as string}</div>}
            <div style={{ opacity: 0.5, fontSize: 9.5, marginTop: 4 }}>
              {ev.latitude?.toFixed(3)}°, {ev.longitude?.toFixed(3)}°
            </div>
          </div>
        );
      })()}
    </div>
  );
}
