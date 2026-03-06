import './App.css';
import GlobeCanvas from './components/Globe/GlobeCanvas';
import HUDOverlay from './components/HUD/HUDOverlay';
import SidePanel from './components/Panel/SidePanel';
import LayerControls from './components/Controls/LayerControls';
import TimelineScrubber from './components/Timeline/TimelineScrubber';

/**
 * Root layout — components stack over the globe via absolute/fixed positioning:
 *
 *  ┌────────────────────────────────────────────┐
 *  │  GlobeCanvas (z:0, fixed, fills screen)    │
 *  │  HUDOverlay  (z:10, top corners)           │
 *  │  LayerControls (z:20, left edge)           │
 *  │  SidePanel   (z:20, right edge)            │
 *  │  TimelineScrubber (z:20, bottom)           │
 *  └────────────────────────────────────────────┘
 */
export default function App() {
  return (
    <div className="nexus-root">
      {/* Layer 0 — 3-D globe fills the viewport */}
      <GlobeCanvas />

      {/* Layer 10 — HUD telemetry overlay */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 10, pointerEvents: 'none' }}>
        <HUDOverlay />
      </div>

      {/* Layer 20 — interactive panels */}
      <div style={{ position: 'fixed', top: 0, left: 0, height: '100%', zIndex: 20 }}>
        <LayerControls />
      </div>

      <div style={{ position: 'fixed', top: 0, right: 0, height: '100%', zIndex: 20 }}>
        <SidePanel />
      </div>

      <div style={{ position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 20 }}>
        <TimelineScrubber />
      </div>
    </div>
  );
}
