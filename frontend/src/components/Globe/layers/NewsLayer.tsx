/**
 * NewsLayer — renders news events as pulsing HTML markers on the Globe.
 *
 * Uses Globe.GL's htmlElementsData API (separate from FlightLayer's
 * customLayerData, so no conflicts).
 *
 * Visual rules:
 *  - Neon cyan (#00f0ff) pulsing dots, size ∝ severity
 *  - Multi-source confirmed events (confirmation_count > 2) glow brighter
 *  - BREAKING badge on Tier-1 RSS events less than 15 min old
 *  - Rich hover tooltip: title, source, confirmations, severity bar, time ago
 *  - Click selects event + flies camera to it
 *  - Layer hidden when news toggle is off
 *  - Events fade as they age (CSS opacity on timestamp delta)
 */
import { useEffect, useRef } from 'react';
import { useGlobe } from '../GlobeContext';
import { useHtmlMarkersStore } from '../htmlMarkersStore';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// ── CSS (injected once into <head>) ─────────────────────────────────────────

const STYLE_ID = 'nexus-news-layer-styles';

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .nn-wrap {
      position: relative;
      cursor: pointer;
      pointer-events: all;
    }
    .nn-dot {
      border-radius: 50%;
      background: #00f0ff;
      box-shadow: 0 0 6px #00f0ff, 0 0 12px rgba(0,240,255,0.4);
      position: absolute;
      top: 50%; left: 50%;
      animation: nn-pulse 2.4s ease-in-out infinite;
      transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .nn-dot.sev5 { animation-duration: 0.9s; }
    .nn-dot.sev4 { animation-duration: 1.2s; }
    .nn-dot.sev3 { animation-duration: 1.8s; }
    .nn-dot.sev2 { animation-duration: 2.4s; }
    .nn-dot.sev1 { animation-duration: 3.2s; }
    .nn-dot.confirmed {
      box-shadow: 0 0 10px #00f0ff, 0 0 22px rgba(0,240,255,0.7), 0 0 36px rgba(0,240,255,0.35);
      animation-name: nn-pulse-bright;
    }
    .nn-dot.breaking {
      animation-name: nn-pulse-break;
    }
    .nn-dot.selected {
      background: #fff !important;
      box-shadow: 0 0 14px #00f0ff, 0 0 28px #00f0ff, 0 0 44px rgba(0,240,255,0.8) !important;
      transform: translate(-50%, -50%) scale(1.6) !important;
    }
    .nn-wrap:hover .nn-dot:not(.selected) {
      transform: translate(-50%, -50%) scale(1.35) !important;
    }
    .nn-badge-break {
      position: absolute;
      bottom: 100%;
      left: 50%;
      transform: translateX(-50%);
      margin-bottom: 2px;
      background: #ff2244;
      color: #fff;
      font-family: 'JetBrains Mono', monospace;
      font-size: 7px;
      font-weight: 700;
      letter-spacing: 0.1em;
      padding: 1px 4px;
      border-radius: 2px;
      white-space: nowrap;
      pointer-events: none;
      animation: nn-break-flash 0.9s ease-in-out infinite;
    }
    .nn-tip {
      display: none;
      position: absolute;
      bottom: calc(100% + 6px);
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.93);
      border: 1px solid rgba(0,240,255,0.55);
      padding: 7px 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 10.5px;
      line-height: 1.55;
      color: #b0eeff;
      border-radius: 3px;
      pointer-events: none;
      white-space: nowrap;
      z-index: 9999;
      min-width: 180px;
      max-width: 300px;
      white-space: normal;
      word-break: break-word;
      box-shadow: 0 2px 16px rgba(0,0,0,0.7);
    }
    .nn-wrap:hover .nn-tip { display: block; }
    @keyframes nn-pulse {
      0%, 100% { transform: translate(-50%, -50%) scale(1.0); opacity: 0.9; }
      50%       { transform: translate(-50%, -50%) scale(1.22); opacity: 0.7; }
    }
    @keyframes nn-pulse-bright {
      0%, 100% { transform: translate(-50%, -50%) scale(1.0); opacity: 1.0; }
      50%       { transform: translate(-50%, -50%) scale(1.30); opacity: 0.9; }
    }
    @keyframes nn-pulse-break {
      0%, 100% { transform: translate(-50%, -50%) scale(1.0); }
      50%       { transform: translate(-50%, -50%) scale(1.45); }
    }
    @keyframes nn-break-flash {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.55; }
    }
  `;
  document.head.appendChild(style);
}

// ── Constants ────────────────────────────────────────────────────────────────

const TIER1_SOURCES = new Set(['rss_wires', 'bbc', 'reuters', 'ap', 'aljazeera']);
const BREAKING_MAX_AGE_MS = 15 * 60 * 1000; // 15 minutes
const MAX_AGE_FADE_MS = 12 * 60 * 60 * 1000; // fade to 20% over 12h

/** Base diameter (px) per severity level */
const SEV_SIZE: Record<number, number> = { 1: 6, 2: 8, 3: 11, 4: 15, 5: 20 };

// ── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return `${Math.floor(diff / 1_000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function ageOpacity(ts: number): number {
  const age = Date.now() - ts;
  if (age <= 0) return 1;
  return Math.max(0.20, 1 - age / MAX_AGE_FADE_MS);
}

function buildTooltipHtml(ev: GlobeEvent): string {
  const meta = ev.metadata as Record<string, unknown>;
  const confirmCount = Number(meta.confirmation_count ?? 1);
  const confirmedBy = Array.isArray(meta.confirmed_by)
    ? (meta.confirmed_by as string[]).join(', ')
    : '';
  const sevBar = '█'.repeat(ev.severity) + '░'.repeat(5 - ev.severity);
  const aiSummary = typeof meta.ai_summary === 'string' && meta.ai_summary
    ? `<div style="color:#b0eeff;margin-top:4px;font-size:10px;opacity:0.9">${meta.ai_summary.substring(0, 120)}${meta.ai_summary.length > 120 ? '…' : ''}</div>`
    : '';
  const confirmLine = confirmCount > 1
    ? `<div style="color:#00ff88">✓ ${confirmCount} source${confirmCount > 1 ? 's' : ''}${confirmedBy ? ': ' + confirmedBy : ''}</div>`
    : '';

  // For GDELT events show the source domain ("via reuters.com") instead of "gdelt"
  const sourceDomain = typeof meta.source_domain === 'string' && meta.source_domain
    ? meta.source_domain
    : null;
  const sourceLabel = sourceDomain ? `via ${sourceDomain}` : ev.source;

  // If this is a URL-slug-derived title we may want to show the geo context below
  const locationName = typeof meta.location_name === 'string' && meta.location_name ? meta.location_name : null;
  const locationLine = locationName && ev.source === 'gdelt'
    ? `<div style="color:rgba(0,240,255,0.38);font-size:9.5px;margin-top:1px">📍 ${locationName}</div>`
    : '';

  return `
    <div style="color:#00f0ff;font-weight:700;margin-bottom:3px">${ev.title.substring(0, 90)}${ev.title.length > 90 ? '…' : ''}</div>
    <div style="color:rgba(0,240,255,0.55)">${sourceLabel} · ${timeAgo(ev.timestamp)}</div>
    ${locationLine}
    ${confirmLine}
    <div style="color:rgba(0,240,255,0.45);margin-top:2px">${sevBar} ${ev.severity}/5</div>
    ${aiSummary}
  `;
}

// ── Element factory / updater ────────────────────────────────────────────────

type MarkerDatum = { ev: GlobeEvent; el: HTMLElement };

function createMarkerElement(
  ev: GlobeEvent,
  isSelected: boolean,
  onClickCb: (ev: GlobeEvent) => void,
): HTMLElement {
  const meta = ev.metadata as Record<string, unknown>;
  const now = Date.now();
  const isBreaking = TIER1_SOURCES.has(ev.source) && (now - ev.timestamp) < BREAKING_MAX_AGE_MS;
  const isConfirmed = Number(meta.confirmation_count ?? 1) > 2;
  const size = SEV_SIZE[ev.severity] ?? 10;
  const opacity = ageOpacity(ev.timestamp);

  const wrap = document.createElement('div');
  wrap.className = 'nn-wrap';
  wrap.style.width = `${size}px`;
  wrap.style.height = `${size}px`;
  wrap.style.opacity = String(opacity);

  // BREAKING badge
  if (isBreaking) {
    const badge = document.createElement('div');
    badge.className = 'nn-badge-break';
    badge.textContent = 'BREAKING';
    wrap.appendChild(badge);
  }

  // Dot
  const dot = document.createElement('div');
  let dotClass = 'nn-dot';
  dotClass += ` sev${ev.severity}`;
  if (isConfirmed) dotClass += ' confirmed';
  if (isBreaking) dotClass += ' breaking';
  if (isSelected) dotClass += ' selected';
  dot.className = dotClass;
  dot.style.width = `${size}px`;
  dot.style.height = `${size}px`;
  dot.style.marginLeft = `${-size / 2}px`;
  dot.style.marginTop = `${-size / 2}px`;
  wrap.appendChild(dot);

  // Tooltip
  const tip = document.createElement('div');
  tip.className = 'nn-tip';
  tip.innerHTML = buildTooltipHtml(ev);
  wrap.appendChild(tip);

  // Click
  wrap.addEventListener('click', (e) => {
    e.stopPropagation();
    onClickCb(ev);
  });

  return wrap;
}

function updateMarkerElement(
  el: HTMLElement,
  ev: GlobeEvent,
  isSelected: boolean,
): void {
  const meta = ev.metadata as Record<string, unknown>;
  const now = Date.now();
  const isBreaking = TIER1_SOURCES.has(ev.source) && (now - ev.timestamp) < BREAKING_MAX_AGE_MS;
  const isConfirmed = Number(meta.confirmation_count ?? 1) > 2;

  // Opacity (age fade)
  el.style.opacity = String(ageOpacity(ev.timestamp));

  // Update dot classes (can change when AI enriches)
  const dot = el.querySelector('.nn-dot') as HTMLElement | null;
  if (dot) {
    let dotClass = 'nn-dot';
    dotClass += ` sev${ev.severity}`;
    if (isConfirmed) dotClass += ' confirmed';
    if (isBreaking) dotClass += ' breaking';
    if (isSelected) dotClass += ' selected';
    dot.className = dotClass;
  }

  // Update tooltip (AI may have added summary since last render)
  const tip = el.querySelector('.nn-tip') as HTMLElement | null;
  if (tip) tip.innerHTML = buildTooltipHtml(ev);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function NewsLayer() {
  const globe         = useGlobe();
  const news          = useLayerData('news');
  const isVisible     = useGlobeStore((s) => s.layers.news);
  const selectEvent   = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);
  const setLayer      = useHtmlMarkersStore((s) => s.setLayer);

  // Use a ref so click handlers always get the latest globe without needing
  // globe in the marker-build effect dependency array.
  const globeRef = useRef(globe);
  globeRef.current = globe;

  // Stable element cache: survives re-renders so DOM elements are reused
  const elemCache = useRef<Map<string, HTMLElement>>(new Map());

  // Inject CSS once
  useEffect(() => { ensureStyles(); }, []);

  // Clear layer on unmount
  useEffect(() => () => { setLayer('news', []); }, [setLayer]);

  useEffect(() => {
    if (!isVisible) {
      setLayer('news', []);
      return;
    }

    const cache = elemCache.current;
    const usedIds = new Set<string>();

    // Skip ungeolocated events (lat=0, lng=0 means the backend had no coordinates
    // — typically RSS wire stories where AI geocoding hasn't run yet).
    const geolocated = news.filter(
      (ev) => !(ev.latitude === 0 && ev.longitude === 0),
    );

    const data: MarkerDatum[] = geolocated.map((ev) => {
      usedIds.add(ev.id);
      const isSelected = ev.id === selectedEventId;

      const existing = cache.get(ev.id);
      if (existing) {
        updateMarkerElement(existing, ev, isSelected);
        return { ev, el: existing };
      }

      // Create new element
      const el = createMarkerElement(ev, isSelected, (clicked) => {
        selectEvent(clicked.id);
        globeRef.current?.pointOfView(
          { lat: clicked.latitude, lng: clicked.longitude, altitude: 1.5 },
          800,
        );
      });
      cache.set(ev.id, el);
      return { ev, el };
    });

    // Evict stale cache entries
    for (const id of cache.keys()) {
      if (!usedIds.has(id)) cache.delete(id);
    }

    // Push to shared store — HtmlLayerSync merges + calls globe.htmlElementsData()
    setLayer(
      'news',
      data.map((d) => ({ el: d.el, lat: d.ev.latitude, lng: d.ev.longitude, alt: 0.01 })),
    );
  }, [news, isVisible, selectEvent, selectedEventId, setLayer]);

  return null;
}

