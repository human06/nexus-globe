import { Component, type ReactNode, type ErrorInfo } from 'react';
import './App.css';
import GlobeCanvas from './components/Globe/GlobeCanvas';
import HUDOverlay from './components/HUD/HUDOverlay';
import NewsTicker from './components/HUD/NewsTicker';
import SidePanel from './components/Panel/SidePanel';
import LayerControls from './components/Controls/LayerControls';
import { useWebSocket } from './hooks/useWebSocket';

// ── Error boundary — shows crash details instead of blank screen ─────────────
interface EBState { error: Error | null }
class ErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: null };
  static getDerivedStateFromError(e: Error) { return { error: e }; }
  componentDidCatch(e: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', e, info.componentStack);
  }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div style={{
        position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: '#0a0a0f', color: '#ff2244',
        fontFamily: 'monospace', padding: '2rem', gap: '1rem',
      }}>
        <div style={{ fontSize: '1.2rem', letterSpacing: '0.2em' }}>NEXUS GLOBE — RENDER ERROR</div>
        <pre style={{
          background: '#12121a', padding: '1rem', borderRadius: 4,
          border: '1px solid #ff2244', maxWidth: '80vw', overflow: 'auto',
          fontSize: '0.8rem', color: '#ff8899', whiteSpace: 'pre-wrap',
        }}>{error.message}\n\n{error.stack}</pre>
        <button
          onClick={() => this.setState({ error: null })}
          style={{ background: '#ff2244', color: '#fff', border: 'none', padding: '0.5rem 2rem', cursor: 'pointer' }}
        >Retry</button>
      </div>
    );
  }
}

/**
 * Root layout — components stack over the globe via absolute/fixed positioning:
 *
 *  ┌────────────────────────────────────────────┐
 *  │  GlobeCanvas (z:0, fixed, fills screen)    │
 *  │  HUDOverlay  (z:10, top corners)           │
 *  │  LayerControls (z:20, left edge)           │
 *  │  SidePanel   (z:20, right edge)            │
 *  └────────────────────────────────────────────┘
 */
function AppInner() {
  // Starts the persistent WebSocket connection and feeds data into the store
  useWebSocket();

  return (
    <div className="nexus-root">
      {/* Layer 0 — 3-D globe fills the viewport */}
      <GlobeCanvas />

      {/* Layer 10 — HUD telemetry overlay (pointer-events:none inside) */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 10, pointerEvents: 'none' }}>
        <HUDOverlay />
      </div>

      {/* Layer 20 — interactive panels */}
      <div style={{ position: 'fixed', top: 0, left: 0, height: '100%', zIndex: 20, pointerEvents: 'none', display: 'flex', alignItems: 'center' }}>
        <LayerControls />
      </div>

      <div style={{ position: 'fixed', top: 0, right: 0, height: '100%', zIndex: 20, pointerEvents: 'none' }}>
        <SidePanel />
      </div>

      {/* Layer 30 — News Ticker at bottom (has its own pointer-events: auto) */}
      <NewsTicker />
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AppInner />
    </ErrorBoundary>
  );
}

