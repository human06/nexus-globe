/**
 * GlobeCanvas — core 3D globe with cyberpunk theme.
 *
 * - Globe.GL rendered into a ref'd <div>, filling the viewport.
 * - NASA night-lights earth texture, star-field background.
 * - Country polygon borders in neon-cyan.
 * - Atmospheric glow effect.
 * - Slow auto-rotation that pauses on user interaction.
 * - GlobeContext provides the live instance to all child layer components.
 */
import { useEffect, useRef, useState } from 'react';
import Globe from 'globe.gl';
import { GlobeContext, type GlobeInstance } from './GlobeContext';
import FlightLayer from './layers/FlightLayer';

// Auto-rotate speed (OrbitControls unit: full rotations per minute × 2)
// We want ~3 min/rotation → 0.33
const AUTO_ROTATE_SPEED = 0.33;
// Delay after the user stops interacting before rotation resumes (ms)
const RESUME_DELAY_MS = 2500;

export default function GlobeCanvas() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [globeInstance, setGlobeInstance] = useState<GlobeInstance | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  // Use a ref to toggle from event handlers without stale-closure issues
  const autoRotateRef = useRef(true);
  const resumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── Instantiate Globe.GL ──────────────────────────────────────────────────
    let globe: GlobeInstance;
    try {
      globe = Globe()(container)
        .width(window.innerWidth)
        .height(window.innerHeight)
        .globeImageUrl('/textures/earth-dark.jpg')
        .backgroundImageUrl('/textures/night-sky.png')
        .atmosphereColor('#00f0ff')
        .atmosphereAltitude(0.25)
        .pointOfView({ lat: 20, lng: 0, altitude: 2.5 }, 0);
    } catch (err) {
      console.error('[GlobeCanvas] Globe.GL init failed:', err);
      setIsLoaded(true);
      return;
    }

    // ── Auto-rotation ─────────────────────────────────────────────────────────
    const ctrl = globe.controls();
    ctrl.autoRotate = true;
    ctrl.autoRotateSpeed = AUTO_ROTATE_SPEED;
    ctrl.enableDamping = true;
    ctrl.dampingFactor = 0.08;

    // ── Pause / resume on user interaction ────────────────────────────────────
    const pauseRotation = () => {
      ctrl.autoRotate = false;
      autoRotateRef.current = false;
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
    };

    const scheduleResume = () => {
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = setTimeout(() => {
        ctrl.autoRotate = true;
        autoRotateRef.current = true;
      }, RESUME_DELAY_MS);
    };

    container.addEventListener('mousedown', pauseRotation);
    container.addEventListener('touchstart', pauseRotation, { passive: true });
    container.addEventListener('mouseup', scheduleResume);
    container.addEventListener('touchend', scheduleResume);

    // ── Load country polygons ─────────────────────────────────────────────────
    fetch('/data/countries.geojson')
      .then((r) => r.json())
      .then((geo: { features: object[] }) => {
        globe
          .polygonsData(geo.features)
          .polygonCapColor(() => 'rgba(0, 0, 0, 0)')
          .polygonSideColor(() => 'rgba(0, 240, 255, 0.04)')
          .polygonStrokeColor(() => '#00f0ff')
          .polygonAltitude(0.001);
        setIsLoaded(true);
      })
      .catch((err) => {
        console.warn('[GlobeCanvas] Failed to load countries.geojson:', err);
        setIsLoaded(true); // Globe is usable without country borders
      });

    // ── Responsive resize ─────────────────────────────────────────────────────
    const onResize = () => {
      globe.width(window.innerWidth).height(window.innerHeight);
    };
    window.addEventListener('resize', onResize);

    // ── Expose instance to child layers via context ───────────────────────────
    // Globe.GL returns a callable function; wrap in arrow so React doesn't
    // treat it as a state-updater callback: setState(fn) → fn(prevState).
    setGlobeInstance(() => globe);

    return () => {
      window.removeEventListener('resize', onResize);
      container.removeEventListener('mousedown', pauseRotation);
      container.removeEventListener('touchstart', pauseRotation);
      container.removeEventListener('mouseup', scheduleResume);
      container.removeEventListener('touchend', scheduleResume);
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      globe._destructor();
    };
  }, []); // only run once on mount

  return (
    <GlobeContext.Provider value={globeInstance}>
      {/* Loading splash — shown until country GeoJSON arrives */}
      {!isLoaded && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1,
            background: 'var(--bg-primary)',
            pointerEvents: 'none',
          }}
        >
          <span
            className="neon-text"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(1rem, 4vw, 2rem)',
              letterSpacing: '0.4em',
              textTransform: 'uppercase',
              animation: 'nexus-pulse 1s ease-in-out infinite',
            }}
          >
            INITIALIZING...
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              color: 'rgba(0, 240, 255, 0.4)',
              marginTop: '1rem',
              letterSpacing: '0.2em',
            }}
          >
            NEXUS GLOBE v1.0
          </span>
        </div>
      )}

      {/* Globe mount point — Globe.GL renders a canvas inside this div */}
      <div
        ref={containerRef}
        id="globe-canvas"
        style={{ position: 'fixed', inset: 0, zIndex: 0 }}
      />

      {/* Data layers — rendered as imperative effects, return null */}
      {globeInstance && <FlightLayer />}
    </GlobeContext.Provider>
  );
}

