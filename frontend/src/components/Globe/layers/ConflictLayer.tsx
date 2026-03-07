/**
 * ConflictLayer — renders ACLED conflict events on Globe.GL.
 *
 * Visuals:
 *  - Battle events: orange (#ff6600) points, size proportional to severity
 *  - Explosions: red (#ff2244) larger points
 *  - Civilian violence: orange-red (#ff4422)
 *  - Protests/riots: yellow-orange (#ffaa00)
 *  - Strategic: dim grey-orange (#996644)
 *  - High-severity active warzones (severity ≥ 4): pulsing rings
 *  - Selected event: cyan (#00e5ff), 2× scale, pulsing ring
 *  - HTML tooltips: event type, actors, fatalities, date, location
 *  - Layer hides when conflicts toggle is off
 *
 * Writes into pointMarkerStore (conflict key) — merged by PointsLayerSync,
 * RingsLayerSync into the single globe.gl channels.
 *
 * Data: useLayerData('conflict') ← WebSocket 'acled' channel (hourly update).
 * Metadata fields: category, fatalities, actor1, actor2, location, country,
 *                  admin1, event_date, event_type, sub_event_type, notes.
 */
import { useEffect } from 'react';
import { useLayerData } from '../../../hooks/useLayerData';
import { useGlobeStore } from '../../../stores/globeStore';
import { usePointMarkerStore } from '../pointMarkerStore';
import type { PointDatum, RingDatum } from '../pointMarkerStore';
import type { GlobeEvent } from '../../../types/events';

// ── Color helpers ─────────────────────────────────────────────────────────────

function conflictColor(ev: GlobeEvent, selectedId: string | null): string {
  if (ev.id === selectedId) return '#00e5ff';
  const cat = (ev.category ?? '').toLowerCase();
  if (cat === 'battle')            return '#ff6600';
  if (cat === 'explosion')         return '#ff2244';
  if (cat === 'civilian_violence') return '#ff4422';
  if (cat === 'riot')              return '#ffaa00';
  if (cat === 'protest')           return '#ffcc44';
  if (cat === 'strategic')         return '#999944';
  return '#ff6600'; // default orange
}

function conflictRadius(ev: GlobeEvent, selectedId: string | null): number {
  if (ev.id === selectedId) return 1.2;
  // Scale with severity: sev 1→0.25, 5→0.8 with fatality bonus
  const base = 0.15 + ev.severity * 0.13;
  const meta = ev.metadata as Record<string, unknown>;
  const fatalities = Number(meta?.fatalities ?? 0);
  const bonus = fatalities > 50 ? 0.25 : fatalities > 10 ? 0.12 : 0;
  return Math.min(1.0, base + bonus);
}

// ── Tooltip factory ───────────────────────────────────────────────────────────

function buildLabel(ev: GlobeEvent): string {
  const meta       = ev.metadata as Record<string, unknown>;
  const eventType  = String(meta?.event_type  ?? ev.category ?? '—');
  const subType    = String(meta?.sub_event_type ?? '');
  const actor1     = String(meta?.actor1      ?? '—');
  const actor2     = String(meta?.actor2      ?? '').trim();
  const fatalities = Number(meta?.fatalities  ?? 0);
  const eventDate  = String(meta?.event_date  ?? '—');
  const location   = String(meta?.location    ?? '');
  const admin1     = String(meta?.admin1      ?? '');
  const country    = String(meta?.country     ?? '');
  const locParts   = [location, admin1, country].filter(Boolean);
  const locStr     = locParts.join(', ') || '—';

  // Severity bar (■ filled, □ empty)
  const bars = '■'.repeat(ev.severity) + '□'.repeat(5 - ev.severity);

  const fatal = fatalities > 0
    ? `<span style="color:#ff4444">${fatalities} fatalities</span><br/>`
    : '';

  const actorsRow = actor2
    ? `${actor1} <span style="color:#ff6600">vs</span> ${actor2}`
    : actor1;

  return `
    <div style="
      background:rgba(0,0,0,.92);border:1px solid #ff6600;
      padding:7px 10px;font:11px/1.6 'JetBrains Mono',monospace;
      color:#ffcc88;border-radius:2px;pointer-events:none;
      min-width:200px;max-width:280px;
    ">
      <b style="font-size:11.5px;color:#ff6600;letter-spacing:.04em">
        ${eventType}${subType ? ' · ' + subType : ''}
      </b><br/>
      <span style="color:rgba(255,102,0,.7);font-size:10px">${ev.title.slice(0, 120)}</span><br/>
      <hr style="border:none;border-top:1px solid rgba(255,102,0,.25);margin:4px 0"/>
      ${fatal}
      ${actorsRow}<br/>
      ${locStr}<br/>
      <span style="color:#ff6600;letter-spacing:.05em;font-size:10px">
        SEV ${bars} · ${eventDate}
      </span>
    </div>`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ConflictLayer() {
  const conflicts       = useLayerData('conflict');
  const isVisible       = useGlobeStore((s) => s.layers.conflicts);
  const selectEvent     = useGlobeStore((s) => s.selectEvent);
  const selectedEventId = useGlobeStore((s) => s.selectedEventId);

  const setPoints = usePointMarkerStore((s) => s.setPoints);
  const setRings  = usePointMarkerStore((s) => s.setRings);

  // Listen for globe-point-click events dispatched by PointsLayerSync
  useEffect(() => {
    const handler = (e: Event) => {
      const pd = (e as CustomEvent<PointDatum>).detail;
      if (pd.layerKey === 'conflict') selectEvent(pd.ev.id);
    };
    window.addEventListener('globe-point-click', handler);
    return () => window.removeEventListener('globe-point-click', handler);
  }, [selectEvent]);

  // ── Point markers ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isVisible) {
      setPoints('conflict', []);
      return;
    }
    const data: PointDatum[] = conflicts.map((ev) => ({
      ev,
      lat:      ev.latitude,
      lng:      ev.longitude,
      alt:      0.001,
      radius:   conflictRadius(ev, selectedEventId),
      color:    conflictColor(ev, selectedEventId),
      label:    buildLabel(ev),
      layerKey: 'conflict' as const,
    }));
    setPoints('conflict', data);
  }, [conflicts, isVisible, selectedEventId, setPoints]);

  // ── Pulsing rings for high-severity events (sev ≥ 4) ─────────────────────
  useEffect(() => {
    if (!isVisible) {
      setRings('conflict', []);
      return;
    }

    const highSev = conflicts.filter(
      (ev) => ev.severity >= 4 || ev.id === selectedEventId,
    );

    const rings: RingDatum[] = highSev.map((ev) => {
      const isSelected = ev.id === selectedEventId;
      return {
        lat:       ev.latitude,
        lng:       ev.longitude,
        maxRadius: isSelected ? 5.0 : 2.5 + ev.severity * 0.5,
        color:     (t: number) =>
          isSelected
            ? `rgba(0,229,255,${Math.max(0, 1 - t * 1.2)})`
            : `rgba(255,102,0,${Math.max(0, 0.8 - t * 1.1)})`,
        speed:     0.8,
        period:    2000,
        layerKey:  'conflict' as const,
      };
    });
    setRings('conflict', rings);
  }, [conflicts, isVisible, selectedEventId, setRings]);

  return null;
}
