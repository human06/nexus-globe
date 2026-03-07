/**
 * DisasterLayer — renders disaster events (earthquakes, wildfires, storms,
 * volcanoes, floods) as HTML markers on the Globe.
 *
 * Writes into the shared `htmlMarkersStore` so that `HtmlLayerSync`
 * can combine disasters + news into a single `globe.htmlElementsData()` call.
 *
 * Visual lang:
 *  Earthquake    — concentric red expanding rings, count = severity
 *  Wildfire      — flickering red-orange dot with position jitter
 *  Severe storm  — semi-transparent blue-grey circle + dotted trail
 *  Volcano       — large pulsing bright-red dot
 *  Flood         — low-opacity blue expanding area
 */
import { useEffect, useRef } from 'react';
import { useGlobe } from '../GlobeContext';
import { useHtmlMarkersStore } from '../htmlMarkersStore';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── CSS injection ────────────────────────────────────────────────────────────

const STYLE_ID = 'nexus-disaster-layer-styles';

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .nd-wrap {
      position: relative;
      cursor: pointer;
      pointer-events: all;
    }
    .nd-wrap:hover .nd-tip { display: block; }

    .nd-tip {
      display: none;
      position: absolute;
      bottom: calc(100% + 6px);
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.93);
      border: 1px solid rgba(255,50,50,0.55);
      padding: 7px 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 10.5px;
      line-height: 1.55;
      color: #ffd0d0;
      border-radius: 3px;
      pointer-events: none;
      z-index: 9999;
      min-width: 180px;
      max-width: 260px;
      white-space: normal;
      word-break: break-word;
      box-shadow: 0 2px 16px rgba(0,0,0,0.7);
    }

    /* Earthquake rings */
    .nd-ring {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      border: 2px solid #ff2244;
      transform: translate(-50%, -50%) scale(0.1);
      opacity: 0;
      animation: nd-quake-ring 2.2s ease-out infinite;
    }
    .nd-ring-core {
      position: absolute;
      top: 50%; left: 50%;
      width: 6px; height: 6px;
      margin-left: -3px; margin-top: -3px;
      border-radius: 50%;
      background: #ff2244;
      box-shadow: 0 0 8px #ff2244;
    }
    @keyframes nd-quake-ring {
      0%   { transform: translate(-50%,-50%) scale(0.1); opacity: 0.85; }
      100% { transform: translate(-50%,-50%) scale(2.8); opacity: 0; }
    }

    /* Wildfire */
    .nd-fire-dot {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      transform: translate(-50%, -50%);
      animation: nd-fire-flicker 0.6s ease-in-out infinite alternate;
    }
    @keyframes nd-fire-flicker {
      0%   { background:#ff2244; box-shadow:0 0 8px #ff2244,0 0 18px rgba(255,50,50,.6);  transform:translate(-50%,-50%) scale(1.00); }
      50%  { background:#ff6600; box-shadow:0 0 12px #ff6600,0 0 24px rgba(255,100,0,.5); transform:translate(-51%,-49%) scale(1.15); }
      100% { background:#ffaa00; box-shadow:0 0 6px #ff8800,0 0 14px rgba(255,140,0,.4);  transform:translate(-49%,-51%) scale(0.92); }
    }

    /* Volcano */
    .nd-volcano-dot {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      background: #ff2244;
      box-shadow: 0 0 10px #ff2244, 0 0 22px rgba(255,50,50,.6);
      transform: translate(-50%, -50%);
      animation: nd-volcano-pulse 1.4s ease-in-out infinite;
    }
    @keyframes nd-volcano-pulse {
      0%,100% { transform:translate(-50%,-50%) scale(1.0); opacity:1.0; }
      50%      { transform:translate(-50%,-50%) scale(1.3); opacity:0.75; }
    }

    /* Severe storm */
    .nd-storm-circle {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      background: rgba(100,140,200,.18);
      border: 1.5px solid rgba(120,160,220,.65);
      transform: translate(-50%, -50%);
      animation: nd-storm-pulse 3s ease-in-out infinite;
    }
    @keyframes nd-storm-pulse {
      0%,100% { transform:translate(-50%,-50%) scale(1.0);  opacity:0.85; }
      50%      { transform:translate(-50%,-50%) scale(1.18); opacity:0.6; }
    }

    /* Flood */
    .nd-flood-circle {
      position: absolute;
      top: 50%; left: 50%;
      border-radius: 50%;
      background: rgba(20,80,255,.15);
      border: 1.5px solid rgba(40,100,255,.45);
      transform: translate(-50%, -50%);
      animation: nd-flood-expand 4s ease-in-out infinite;
    }
    @keyframes nd-flood-expand {
      0%,100% { transform:translate(-50%,-50%) scale(1.0);  opacity:0.7; }
      50%      { transform:translate(-50%,-50%) scale(1.25); opacity:0.4; }
    }

    /* Selected overlay */
    .nd-selected-ring {
      position: absolute;
      top: 50%; left: 50%;
      width: 28px; height: 28px;
      margin-left: -14px; margin-top: -14px;
      border-radius: 50%;
      border: 2px solid #ff8800;
      box-shadow: 0 0 10px #ff8800;
      animation: nd-selected-pulse 0.8s ease-in-out infinite;
    }
    @keyframes nd-selected-pulse {
      0%,100% { transform:scale(1.0); opacity:1.0; }
      50%      { transform:scale(1.2); opacity:0.7; }
    }
  `;
  document.head.appendChild(style);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const MAX_AGE_FADE_MS = 14 * 24 * 60 * 60 * 1000;

function ageOpacity(ts: number): number {
  return Math.max(0.2, 1 - (Date.now() - ts) / MAX_AGE_FADE_MS);
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 3_600_000)  return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function buildTooltip(ev: GlobeEvent): string {
  const meta    = ev.metadata as Record<string, unknown>;
  const mag     = typeof meta.magnitude === 'number' ? `M${(meta.magnitude as number).toFixed(1)}` : null;
  const depth   = typeof meta.depth_km  === 'number' ? `${(meta.depth_km as number).toFixed(0)} km depth` : null;
  const alert   = typeof meta.alert_level === 'string' ? (meta.alert_level as string).toUpperCase() : null;
  const tsunami = Boolean(meta.tsunami_flag) ? '⚠ TSUNAMI WATCH' : null;
  const cat     = String(meta.eonet_category ?? ev.category ?? ev.type).toUpperCase();
  const extras  = [mag, depth, alert, tsunami].filter(Boolean).join(' · ');
  return `
    <div style="color:#ff6644;font-weight:700;margin-bottom:3px">${ev.title.substring(0, 80)}${ev.title.length > 80 ? '…' : ''}</div>
    <div style="color:rgba(255,180,160,.7)">${cat} · ${timeAgo(ev.timestamp)}</div>
    ${extras ? `<div style="color:#ffaa88;margin-top:2px">${extras}</div>` : ''}
    <div style="color:rgba(255,100,100,.5);margin-top:2px">SEV ${'█'.repeat(ev.severity)}${'░'.repeat(5 - ev.severity)}</div>
  `;
}

// ── Element builders (one per category) ─────────────────────────────────────

function mkEarthquake(ev: GlobeEvent, selected: boolean): HTMLElement {
  const sz = 32 + ev.severity * 6;
  const w  = document.createElement('div');
  w.className = 'nd-wrap';
  w.style.cssText = `width:${sz}px;height:${sz}px;opacity:${ageOpacity(ev.timestamp)}`;
  const core = document.createElement('div');
  core.className = 'nd-ring-core';
  w.appendChild(core);
  for (let i = 0; i < ev.severity; i++) {
    const r = document.createElement('div');
    r.className = 'nd-ring';
    r.style.cssText = `width:${sz}px;height:${sz}px;animation-delay:${i * 0.44}s;animation-duration:${(2.8 - ev.severity * 0.18).toFixed(2)}s`;
    w.appendChild(r);
  }
  if (selected) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; w.appendChild(s); }
  const tip = document.createElement('div'); tip.className = 'nd-tip'; tip.innerHTML = buildTooltip(ev); w.appendChild(tip);
  return w;
}

function mkWildfire(ev: GlobeEvent, selected: boolean): HTMLElement {
  const sz = 8 + ev.severity * 4;
  const w  = document.createElement('div');
  w.className = 'nd-wrap';
  w.style.cssText = `width:${sz * 3}px;height:${sz * 3}px;opacity:${ageOpacity(ev.timestamp)}`;
  const dot = document.createElement('div'); dot.className = 'nd-fire-dot'; dot.style.cssText = `width:${sz}px;height:${sz}px`; w.appendChild(dot);
  if (selected) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; w.appendChild(s); }
  const tip = document.createElement('div'); tip.className = 'nd-tip'; tip.style.borderColor = 'rgba(255,100,0,.55)'; tip.innerHTML = buildTooltip(ev); w.appendChild(tip);
  return w;
}

function mkVolcano(ev: GlobeEvent, selected: boolean): HTMLElement {
  const sz = 14 + ev.severity * 3;
  const w  = document.createElement('div');
  w.className = 'nd-wrap';
  w.style.cssText = `width:${sz * 2}px;height:${sz * 2}px;opacity:${ageOpacity(ev.timestamp)}`;
  const dot = document.createElement('div'); dot.className = 'nd-volcano-dot'; dot.style.cssText = `width:${sz}px;height:${sz}px`; w.appendChild(dot);
  if (selected) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; w.appendChild(s); }
  const tip = document.createElement('div'); tip.className = 'nd-tip'; tip.innerHTML = buildTooltip(ev); w.appendChild(tip);
  return w;
}

function mkStorm(ev: GlobeEvent, selected: boolean): HTMLElement {
  const sz = 30 + ev.severity * 10;
  const w  = document.createElement('div');
  w.className = 'nd-wrap';
  w.style.cssText = `width:${sz}px;height:${sz}px;opacity:${ageOpacity(ev.timestamp)}`;
  const c = document.createElement('div'); c.className = 'nd-storm-circle'; c.style.cssText = `width:${sz}px;height:${sz}px`; w.appendChild(c);
  if (selected) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; w.appendChild(s); }
  const tip = document.createElement('div'); tip.className = 'nd-tip'; tip.innerHTML = buildTooltip(ev); w.appendChild(tip);
  return w;
}

function mkFlood(ev: GlobeEvent, selected: boolean): HTMLElement {
  const sz = 28 + ev.severity * 10;
  const w  = document.createElement('div');
  w.className = 'nd-wrap';
  w.style.cssText = `width:${sz}px;height:${sz}px;opacity:${ageOpacity(ev.timestamp)}`;
  const c = document.createElement('div'); c.className = 'nd-flood-circle'; c.style.cssText = `width:${sz}px;height:${sz}px`; w.appendChild(c);
  if (selected) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; w.appendChild(s); }
  const tip = document.createElement('div'); tip.className = 'nd-tip'; tip.style.borderColor = 'rgba(40,100,255,.55)'; tip.innerHTML = buildTooltip(ev); w.appendChild(tip);
  return w;
}

function mkDisasterEl(ev: GlobeEvent, selected: boolean): HTMLElement {
  const cat = (ev.category ?? '').toLowerCase();
  if (cat.includes('earthquake'))                              return mkEarthquake(ev, selected);
  if (cat.includes('wildfire') || cat.includes('fire'))       return mkWildfire(ev, selected);
  if (cat.includes('volcanic') || cat.includes('volcano'))    return mkVolcano(ev, selected);
  if (cat.includes('storm') || cat.includes('cyclone') || cat.includes('hurricane')) return mkStorm(ev, selected);
  if (cat.includes('flood') || cat.includes('landslide'))     return mkFlood(ev, selected);
  return mkWildfire(ev, selected); // fallback
}

function updateEl(el: HTMLElement, ev: GlobeEvent, selected: boolean): void {
  el.style.opacity = String(ageOpacity(ev.timestamp));
  const tip = el.querySelector('.nd-tip') as HTMLElement | null;
  if (tip) tip.innerHTML = buildTooltip(ev);
  const sel = el.querySelector('.nd-selected-ring');
  if (selected && !sel) { const s = document.createElement('div'); s.className = 'nd-selected-ring'; el.appendChild(s); }
  else if (!selected && sel) sel.remove();
}

// ── Component ────────────────────────────────────────────────────────────────

export default function DisasterLayer() {
  const globe           = useGlobe();
  const disasters       = useLayerData('disaster');
  const isVisible       = useGlobeStore((s) => s.layers.disasters);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);
  const setLayer        = useHtmlMarkersStore((s) => s.setLayer);

  const globeRef  = useRef(globe);
  globeRef.current = globe;
  const elemCache = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => { ensureStyles(); }, []);
  useEffect(() => () => { setLayer('disaster', []); }, [setLayer]);

  useEffect(() => {
    if (!isVisible) { setLayer('disaster', []); return; }

    const cache  = elemCache.current;
    const usedIds = new Set<string>();

    const data = disasters
      .filter((ev) => ev.latitude !== 0 || ev.longitude !== 0) // skip ungeocoded
      .map((ev) => {
        usedIds.add(ev.id);
        const selected = ev.id === selectedEventId;

        const existing = cache.get(ev.id);
        if (existing) {
          updateEl(existing, ev, selected);
          return { el: existing, lat: ev.latitude, lng: ev.longitude, alt: 0.015 };
        }

        const el = mkDisasterEl(ev, selected);
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          selectEvent(ev.id);
          globeRef.current?.pointOfView(
            { lat: ev.latitude, lng: ev.longitude, altitude: 1.8 },
            800,
          );
        });
        cache.set(ev.id, el);
        return { el, lat: ev.latitude, lng: ev.longitude, alt: 0.015 };
      });

    for (const id of cache.keys()) { if (!usedIds.has(id)) cache.delete(id); }

    setLayer('disaster', data);
  }, [disasters, isVisible, selectEvent, selectedEventId, setLayer]);

  return null;
}

