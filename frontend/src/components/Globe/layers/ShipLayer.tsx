/**
 * ShipLayer — renders AIS ship positions as neon-green diamond markers.
 *
 * Writes into the shared `htmlMarkersStore` so `HtmlLayerSync` can combine
 * news + disaster + ship into a single `globe.htmlElementsData()` call.
 *
 * Visual language:
 *   Diamond-shaped marker (rotated square) — neon green `#00ff88`
 *   Heading arrow pointing in vessel direction
 *   Size by type: cargo/tanker (14px) > passenger (12px) > fishing/special (9px)
 *   Ships < 0.5 kts shown dimmed (at anchor)
 *   Selected: pulsing orange ring
 *
 * Ship trail (last 20 positions) is stored in `metadata.trail` and is
 * displayed in the EventDetail panel; a globe path-trail requires a shared
 * pathsData slot (future enhancement — pathsData is currently owned by FlightLayer).
 */
import { useEffect, useRef } from 'react';
import { useGlobe } from '../GlobeContext';
import { useHtmlMarkersStore } from '../htmlMarkersStore';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── CSS injection ─────────────────────────────────────────────────────────────

const STYLE_ID = 'nexus-ship-layer-styles';

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .ns-wrap {
      position: relative;
      cursor: pointer;
      pointer-events: all;
    }
    .ns-wrap:hover .ns-tip { display: block; }

    .ns-tip {
      display: none;
      position: absolute;
      bottom: calc(100% + 8px);
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.93);
      border: 1px solid rgba(0,255,136,0.5);
      padding: 7px 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 10.5px;
      line-height: 1.55;
      color: #d0ffd8;
      border-radius: 3px;
      pointer-events: none;
      z-index: 9999;
      min-width: 170px;
      max-width: 240px;
      white-space: normal;
      word-break: break-word;
      box-shadow: 0 2px 16px rgba(0,0,0,0.7);
    }

    .ns-diamond {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%) rotate(45deg);
      background: rgba(0, 255, 136, 0.2);
      border: 1.5px solid #00ff88;
      box-shadow: 0 0 7px rgba(0, 255, 136, 0.6);
    }

    /* Heading arrow — rotated via inline style to vessel heading */
    .ns-arrow {
      position: absolute;
      top: 50%; left: 50%;
      width: 0; height: 0;
      pointer-events: none;
    }
    .ns-arrow::after {
      content: '';
      position: absolute;
      top: -15px;
      left: -3px;
      width: 0; height: 0;
      border-left: 3px solid transparent;
      border-right: 3px solid transparent;
      border-bottom: 7px solid #00ff88;
      filter: drop-shadow(0 0 3px #00ff88);
    }

    .ns-selected-ring {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      border: 2px solid #ff8800;
      transform: translate(-50%, -50%);
      animation: ns-sel-pulse 1.2s ease-in-out infinite;
      pointer-events: none;
    }
    @keyframes ns-sel-pulse {
      0%, 100% { opacity: 1;   box-shadow: 0 0 6px #ff8800; }
      50%       { opacity: 0.5; box-shadow: 0 0 14px #ff8800; }
    }
  `;
  document.head.appendChild(style);
}

// ── Sizing by ship category ───────────────────────────────────────────────────

function shipSize(category: string): number {
  const cat = category.toLowerCase();
  if (cat === 'cargo' || cat === 'tanker') return 14;
  if (cat === 'passenger')                 return 12;
  return 9; // fishing, special, unknown
}

// ── DOM builder ───────────────────────────────────────────────────────────────

function mkShipEl(ev: GlobeEvent, isSelected: boolean): HTMLElement {
  const meta    = ev.metadata as Record<string, unknown>;
  const sogKts  = (meta.sog_kts as number | null) ?? (ev.speed ? ev.speed / 1.852 : null);
  const isAnchor = sogKts !== null && sogKts < 0.5;
  const heading = ev.heading ?? (meta.heading as number | null) ?? 0;
  const size    = shipSize(ev.category);
  const outer   = size + 16; // wrapper side (room for selected ring + arrow)

  const wrap = document.createElement('div');
  wrap.className  = 'ns-wrap';
  wrap.style.cssText = `width:${outer}px;height:${outer}px;opacity:${isAnchor ? 0.35 : 1};`;

  // Diamond
  const diamond     = document.createElement('div');
  diamond.className = 'ns-diamond';
  diamond.style.cssText = `width:${size}px;height:${size}px;`;
  wrap.appendChild(diamond);

  // Heading arrow (omit when at anchor)
  if (!isAnchor) {
    const arrow     = document.createElement('div');
    arrow.className = 'ns-arrow';
    arrow.style.transform = `translate(-50%,-50%) rotate(${heading}deg)`;
    wrap.appendChild(arrow);
  }

  // Tooltip
  const name = ev.title.replace(/\s*\(.*?\)\s*$/, '').trim() || `MMSI ${meta.mmsi}`;
  const dest  = meta.destination ? `<br/>→ <b>${meta.destination}</b>` : '';
  const flag  = meta.flag_country ? ` ${meta.flag_country}` : '';
  const tip   = document.createElement('div');
  tip.className = 'ns-tip';
  tip.innerHTML = [
    `<b>${name}</b>${flag}`,
    `${ev.category.toUpperCase()} • ${sogKts !== null ? sogKts.toFixed(1) + ' kts' : 'speed N/A'}`,
    `HDG ${heading}°${dest}`,
  ].join('<br/>');
  wrap.appendChild(tip);

  // Selected ring
  if (isSelected) {
    const ring     = document.createElement('div');
    ring.className = 'ns-selected-ring';
    ring.style.cssText = `width:${size + 14}px;height:${size + 14}px;`;
    wrap.appendChild(ring);
  }

  return wrap;
}

/** Mutate an existing element to reflect updated selection/anchor state. */
function updateEl(el: HTMLElement, ev: GlobeEvent, isSelected: boolean): void {
  const meta    = ev.metadata as Record<string, unknown>;
  const sogKts  = (meta.sog_kts as number | null) ?? (ev.speed ? ev.speed / 1.852 : null);
  const isAnchor = sogKts !== null && sogKts < 0.5;

  el.style.opacity = isAnchor ? '0.35' : '1';

  const existing = el.querySelector('.ns-selected-ring');
  if (isSelected && !existing) {
    const size = shipSize(ev.category);
    const ring = document.createElement('div');
    ring.className = 'ns-selected-ring';
    ring.style.cssText = `width:${size + 14}px;height:${size + 14}px;`;
    el.appendChild(ring);
  } else if (!isSelected && existing) {
    existing.remove();
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

type ShipDatum = { el: HTMLElement; lat: number; lng: number; alt: number };

export default function ShipLayer() {
  const globe  = useGlobe();
  const globeRef = useRef(globe);
  globeRef.current = globe;

  const ships          = useLayerData('ship');
  const isVisible      = useGlobeStore((s) => s.layers.ships);
  const selectEvent    = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);
  const setLayer       = useHtmlMarkersStore((s) => s.setLayer);

  const elemCache = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => { ensureStyles(); }, []);

  // Clear slot on unmount
  useEffect(() => () => { setLayer('ship', []); }, [setLayer]);

  useEffect(() => {
    if (!isVisible) { setLayer('ship', []); return; }

    const data: ShipDatum[] = [];

    for (const ev of ships) {
      // Skip unlocated events
      if (ev.latitude === 0 && ev.longitude === 0) continue;

      const isSel = ev.id === selectedEventId;
      let el = elemCache.current.get(ev.id);

      if (!el) {
        el = mkShipEl(ev, isSel);
        el.addEventListener('click', () => {
          selectEvent(ev);
          globeRef.current?.pointOfView(
            { lat: ev.latitude, lng: ev.longitude, altitude: 1.5 },
            800,
          );
        });
        elemCache.current.set(ev.id, el);
      } else {
        updateEl(el, ev, isSel);
      }

      data.push({ el, lat: ev.latitude, lng: ev.longitude, alt: 0.012 });
    }

    // Prune stale cache entries
    const liveIds = new Set(ships.map((e) => e.id));
    for (const [id] of elemCache.current) {
      if (!liveIds.has(id)) elemCache.current.delete(id);
    }

    setLayer('ship', data);
  }, [ships, isVisible, selectEvent, selectedEventId, setLayer]);

  return null;
}
