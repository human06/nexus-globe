/**
 * ShipLayer — renders AIS ship positions as WebGL Three.js sprites injected
 * directly into Globe.GL's Three.js scene (globe.scene()).
 *
 * Visuals:
 *  - Neon-green top-down ship-hull silhouette (pointed bow, rounded stern)
 *  - Distinctly different from satellite icons (cross/antenna shape)
 *  - sprite.material.rotation = heading_deg → hull points in vessel direction
 *  - Anchored vessels: dimmed opacity (speed < 0.5 kts)
 *  - Selected: brighter, larger, white-rimmed
 *  - Hover tooltip: name, speed, heading, flag, destination
 *  - Click: opens SidePanel with full ShipDetail (MMSI, IMO, ETA, etc.)
 */
import React, { useEffect, useRef, useState } from 'react';
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

// ── Colours ───────────────────────────────────────────────────────────────────

const SHIP_GREEN   = '#00ff88';
const ANCHOR_COLOR = '#336644';

// ── Canvas texture: top-down ship hull silhouette ─────────────────────────────

const _texCache = new Map<string, THREE.CanvasTexture>();

function buildShipTexture(selected = false, anchored = false): THREE.CanvasTexture {
  const cacheKey = `${selected}:${anchored}`;
  if (_texCache.has(cacheKey)) return _texCache.get(cacheKey)!;

  const S   = 64;
  const c   = document.createElement('canvas');
  c.width = S; c.height = S;
  const ctx = c.getContext('2d')!;
  const cx  = S / 2;

  const col = anchored ? ANCHOR_COLOR : SHIP_GREEN;

  // Soft glow halo
  const glow = ctx.createRadialGradient(cx, cx, 2, cx, cx, S * 0.44);
  glow.addColorStop(0,   col + (selected ? 'aa' : '55'));
  glow.addColorStop(0.5, col + (selected ? '44' : '18'));
  glow.addColorStop(1,   'rgba(0,0,0,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, S, S);

  // Ship hull: pointed bow at top, rounded stern at bottom
  ctx.shadowColor = col;
  ctx.shadowBlur  = selected ? 12 : 6;
  ctx.fillStyle   = selected ? '#ffffff' : col;
  ctx.strokeStyle = selected ? '#ffffff' : col;
  ctx.lineWidth   = selected ? 1.5 : 1.0;

  const bowY   = S * 0.10;
  const midY   = S * 0.55;
  const sternY = S * 0.88;
  const hw     = S * 0.16;
  const sw     = S * 0.10;

  ctx.beginPath();
  ctx.moveTo(cx, bowY);
  ctx.bezierCurveTo(cx + hw * 1.2, S * 0.30, cx + hw, midY, cx + sw, sternY);
  ctx.bezierCurveTo(cx + sw * 0.3, sternY + S * 0.04, cx - sw * 0.3, sternY + S * 0.04, cx - sw, sternY);
  ctx.bezierCurveTo(cx - hw, midY, cx - hw * 1.2, S * 0.30, cx, bowY);
  ctx.closePath();

  ctx.globalAlpha = anchored ? 0.5 : selected ? 1.0 : 0.92;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.stroke();

  const tex = new THREE.CanvasTexture(c);
  _texCache.set(cacheKey, tex);
  return tex;
}

// ── LOD scale (world units, sizeAttenuation: true) ───────────────────────────

function shipScale(alt: number, selected: boolean): number {
  const base = alt > 3.0 ? 0.28
             : alt > 2.0 ? 0.36
             : alt > 1.0 ? 0.46
             :             0.58;
  return base * (selected ? 1.8 : 1.0);
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

  const renderCap = cameraAlt > 3.0 ? 800 : cameraAlt > 2.0 ? 2000 : 5000;
  const ships     = useLayerData('ship', renderCap);

  const spritesRef = useRef<THREE.Sprite[]>([]);
  const evMapRef   = useRef<Map<THREE.Sprite, GlobeEvent>>(new Map());
  const groupRef   = useRef<THREE.Group | null>(null);
  const rcRef      = useRef(new THREE.Raycaster());

  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const mouseRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const rafRef   = useRef<number>(0);

  // Clear legacy HTML marker store slot
  useEffect(() => {
    setLayer('ship', []);
    return () => { setLayer('ship', []); };
  }, [setLayer]);

  // ── Build / rebuild sprites ────────────────────────────────────────────────
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const scene = g.scene();

    if (groupRef.current) {
      scene.remove(groupRef.current);
      spritesRef.current.forEach((s) => (s.material as THREE.SpriteMaterial).dispose());
      spritesRef.current = [];
      evMapRef.current.clear();
    }

    if (!isVisible || ships.length === 0) {
      groupRef.current = null;
      return;
    }

    const group   = new THREE.Group();
    group.name    = 'nexus-ship-layer';
    const sprites: THREE.Sprite[]         = [];
    const evMap   = new Map<THREE.Sprite, GlobeEvent>();

    for (const ev of ships) {
      const lat = ev.latitude;
      const lng = ev.longitude;
      if (lat == null || lng == null) continue;

      const meta    = (ev.metadata ?? {}) as Record<string, unknown>;
      const speedKts = Number(meta.sog_kts ?? meta.speed ?? ev.speed ?? 1);
      const heading  = Number(meta.heading ?? ev.heading ?? 0);
      const isAnch   = speedKts < 0.5;
      const isSel    = ev.id === selectedId;

      const tex = buildShipTexture(isSel, isAnch);
      const mat = new THREE.SpriteMaterial({
        map:             tex,
        transparent:     true,
        opacity:         isAnch ? 0.38 : isSel ? 1.0 : 0.80,
        depthWrite:      false,
        sizeAttenuation: true,
      });
      mat.rotation = (heading * Math.PI) / 180;

      const sprite         = new THREE.Sprite(mat);
      sprite.userData.evId = ev.id;
      sprite.scale.setScalar(shipScale(cameraAlt, isSel));

      const { x, y, z } = g.getCoords(lat, lng, 0);
      sprite.position.set(x, y, z);

      group.add(sprite);
      sprites.push(sprite);
      evMap.set(sprite, ev);
    }

    scene.add(group);
    groupRef.current   = group;
    spritesRef.current = sprites;
    evMapRef.current   = evMap;

    return () => {
      scene.remove(group);
      sprites.forEach((s) => (s.material as THREE.SpriteMaterial).dispose());
    };
  }, [ships, isVisible, selectedId, cameraAlt]);

  // ── Canvas click + hover listeners ────────────────────────────────────────
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    const canvas = g.renderer().domElement;

    const onMove = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY };
    };
    canvas.addEventListener('mousemove', onMove, { passive: true });

    // Click opens SidePanel (selectEvent) with full ShipDetail
    const onClick = (e: MouseEvent) => {
      const sprites = spritesRef.current;
      if (!sprites.length || !groupRef.current?.visible) return;
      const rect = canvas.getBoundingClientRect();
      const ndcX = ((e.clientX - rect.left) / rect.width)  * 2 - 1;
      const ndcY = -((e.clientY - rect.top)  / rect.height) * 2 + 1;
      rcRef.current.setFromCamera(new THREE.Vector2(ndcX, ndcY), g.camera());
      const hits = rcRef.current.intersectObjects(sprites, false);
      if (hits.length) {
        const hit = evMapRef.current.get(hits[0].object as THREE.Sprite);
        if (hit) {
          selectEvent(hit.id);
          e.stopPropagation();
        }
      }
    };
    canvas.addEventListener('click', onClick);

    // RAF hover tooltip
    rcRef.current.params.Sprite = { threshold: 0.06 };
    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const g2      = globeRef.current;
      const sprites = spritesRef.current;
      if (!g2 || !sprites.length) return;
      const rect = canvas.getBoundingClientRect();
      const ndcX = ((mouseRef.current.x - rect.left) / rect.width)  * 2 - 1;
      const ndcY = -((mouseRef.current.y - rect.top)  / rect.height) * 2 + 1;
      rcRef.current.setFromCamera(new THREE.Vector2(ndcX, ndcY), g2.camera());
      const hits = rcRef.current.intersectObjects(sprites, false);
      if (hits.length) {
        const ev = evMapRef.current.get(hits[0].object as THREE.Sprite);
        if (ev) {
          setTooltip({ x: mouseRef.current.x, y: mouseRef.current.y, ev });
          canvas.style.cursor = 'pointer';
          return;
        }
      }
      setTooltip(null);
      canvas.style.cursor = '';
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      canvas.removeEventListener('mousemove', onMove);
      canvas.removeEventListener('click', onClick);
    };
  }, [selectEvent]);

  // ── Hover tooltip overlay ─────────────────────────────────────────────────
  return (
    <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 5 }}>
      {tooltip && (() => {
        const ev   = tooltip.ev;
        const meta = (ev.metadata ?? {}) as Record<string, unknown>;
        const spd  = (meta.sog_kts ?? meta.speed ?? ev.speed) as number | undefined;
        const hdg  = (meta.heading ?? ev.heading) as number | undefined;
        return (
          <div style={{
            position:      'fixed',
            left:          tooltip.x + 14,
            top:           tooltip.y - 10,
            background:    'rgba(0,0,0,0.92)',
            border:        `1px solid ${SHIP_GREEN}55`,
            padding:       '7px 11px',
            fontFamily:    "'JetBrains Mono', monospace",
            fontSize:      '10.5px',
            lineHeight:    '1.65',
            color:         '#d0ffd8',
            borderRadius:  3,
            pointerEvents: 'none',
            zIndex:        9999,
            minWidth:      160,
            maxWidth:      240,
            boxShadow:     `0 2px 16px rgba(0,0,0,0.7), 0 0 8px ${SHIP_GREEN}22`,
          }}>
            <div style={{
              color: SHIP_GREEN, fontWeight: 700, marginBottom: 4,
              fontSize: '11px', textShadow: `0 0 6px ${SHIP_GREEN}`,
            }}>
              ⛵ {ev.title.split('—')[0].trim()}
            </div>
            {!!ev.category && (
              <div style={{ opacity: 0.65, textTransform: 'capitalize' }}>
                {ev.category}
              </div>
            )}
            {spd != null && (
              <div style={{ opacity: 0.8 }}>
                {Number(spd).toFixed(1)} kts
                {hdg != null ? `  ·  ${Number(hdg).toFixed(0)}°` : ''}
              </div>
            )}
            {!!meta.flag        && <div style={{ opacity: 0.7 }}>🏴 {meta.flag as string}</div>}
            {!!meta.destination && <div style={{ opacity: 0.65 }}>→ {meta.destination as string}</div>}
            <div style={{ opacity: 0.45, fontSize: '9.5px', marginTop: 5 }}>
              {ev.latitude?.toFixed(3)}°, {ev.longitude?.toFixed(3)}°
            </div>
            <div style={{ opacity: 0.35, fontSize: '9px', marginTop: 2 }}>
              click for full details
            </div>
          </div>
        );
      })()}
    </div>
  );
}
