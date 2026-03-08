/**
 * HeatmapLayer — Globe.GL hexbin density overlay.
 *
 * Story 3.12: When heatmapMode is active, replaces individual markers with a
 * hexagonal event-density heatmap using globe.gl's hexBin layer. The hex color
 * goes from dark-blue (few events) → cyan → green → yellow → red (many).
 * Altitude is proportional to event density, giving a 3-D bar effect.
 */
import { useContext, useEffect } from 'react';
import { GlobeContext } from '../GlobeContext';
import { useGlobeStore } from '../../../stores/globeStore';
import type { GlobeEvent } from '../../../types/events';

// Color gradient: count 0 → max
function densityToColor(count: number, maxCount: number, maxSev: number): string {
  const ratio = maxCount > 0 ? count / maxCount : 0;
  if (ratio < 0.15)  return `rgba(10,10,40,${0.3 + ratio * 2})`;
  if (ratio < 0.35)  return `rgba(0,100,180,${0.5 + ratio})`;
  if (ratio < 0.55)  return `rgba(0,200,200,0.75)`;
  if (ratio < 0.75)  return `rgba(0,240,80,0.82)`;
  if (ratio < 0.9)   return `rgba(255,200,0,0.88)`;
  const sevBoost = maxSev >= 4 ? 1 : 0.9;
  return `rgba(255,${Math.round(50 * (1 - ratio))},0,${sevBoost})`;
}

export default function HeatmapLayer() {
  const globe       = useContext(GlobeContext);
  const heatmapMode = useGlobeStore((s) => s.heatmapMode);
  const events      = useGlobeStore((s) => s.events);
  const layers      = useGlobeStore((s) => s.layers);
  const severityRange = useGlobeStore((s) => s.severityRange);

  useEffect(() => {
    if (!globe) return;

    if (!heatmapMode) {
      // Clear the hexBin layer
      globe.hexBinPointsData([]);
      return;
    }

    // Filter visible events
    const visibleTypes = Object.entries(layers)
      .filter(([, on]) => on)
      .map(([type]) => {
        // Store key → event type mapping
        const map: Record<string, string> = {
          flights: 'flight', news: 'news', ships: 'ship',
          satellites: 'satellite', disasters: 'disaster',
          conflicts: 'conflict', traffic: 'traffic', cameras: 'camera',
        };
        return map[type] ?? type;
      });

    const visible = Array.from(events.values()).filter(
      (ev) =>
        visibleTypes.includes(ev.type) &&
        ev.severity >= severityRange[0] &&
        ev.severity <= severityRange[1],
    );

    if (!visible.length) {
      globe.hexBinPointsData([]);
      return;
    }

    // Configure hexBin layer
    globe
      .hexBinPointsData(visible)
      .hexBinPointLat((d) => (d as GlobeEvent).latitude)
      .hexBinPointLng((d) => (d as GlobeEvent).longitude)
      .hexBinResolution(4)
      .hexBinMerge(false)
      .hexAltitude((d: object) => {
        const bin = d as { points: GlobeEvent[] };
        return Math.min(0.6, bin.points.length * 0.005 + 0.01);
      })
      .hexTopColor((d: object) => {
        const bin = d as { points: GlobeEvent[] };
        const count = bin.points.length;
        const maxSev = Math.max(...bin.points.map((p) => p.severity));
        return densityToColor(count, Math.max(50, count * 2), maxSev);
      })
      .hexSideColor((d: object) => {
        const bin = d as { points: GlobeEvent[] };
        const count = bin.points.length;
        const maxSev = Math.max(...bin.points.map((p) => p.severity));
        return densityToColor(count, Math.max(50, count * 2), maxSev).replace(/,[\d.]+\)$/, ',0.4)');
      })
      .hexLabel((d: object) => {
        const bin = d as { points: GlobeEvent[] };
        const count = bin.points.length;
        const types = bin.points.reduce<Record<string, number>>((acc, p) => {
          acc[p.type] = (acc[p.type] ?? 0) + 1;
          return acc;
        }, {});
        const typeStr = Object.entries(types)
          .sort(([, a], [, b]) => b - a)
          .slice(0, 3)
          .map(([t, n]) => `${n} ${t}`)
          .join(' · ');
        return `<div style="font-family:monospace;font-size:11px;color:#fff;background:rgba(0,0,0,0.7);padding:4px 6px;border-radius:3px;">${count} events<br/>${typeStr}</div>`;
      });

  }, [globe, heatmapMode, events, layers, severityRange]);

  return null;
}
