/**
 * HtmlLayerSync — single component that owns the Globe.GL `htmlElementsData`
 * slot.  Reads from `htmlMarkersStore` (news + disaster + ship arrays) and calls
 * `globe.htmlElementsData()` with their union whenever either changes.
 *
 * Mount exactly once inside <GlobeContext.Provider>.
 */
import { useEffect } from 'react';
import { useGlobe } from './GlobeContext';
import { useHtmlMarkersStore } from './htmlMarkersStore';
import type { HtmlMarkerDatum } from './htmlMarkersStore';

export default function HtmlLayerSync() {
  const globe   = useGlobe();
  const layers  = useHtmlMarkersStore((s) => s.layers);

  useEffect(() => {
    if (!globe) return;

    const combined: HtmlMarkerDatum[] = [
      ...layers.news,
      ...layers.disaster,
      ...layers.ship,
    ];

    globe
      .htmlElementsData(combined)
      .htmlElement((d: object)  => (d as HtmlMarkerDatum).el)
      .htmlLat((d: object)      => (d as HtmlMarkerDatum).lat)
      .htmlLng((d: object)      => (d as HtmlMarkerDatum).lng)
      .htmlAltitude((d: object) => (d as HtmlMarkerDatum).alt ?? 0.01)
      .htmlTransitionDuration(0);
  }, [globe, layers]);

  return null;
}
