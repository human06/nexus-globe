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
import NewsLayer from './layers/NewsLayer';
import DisasterLayer from './layers/DisasterLayer';
import ShipLayer from './layers/ShipLayer';
import SatelliteLayer from './layers/SatelliteLayer';
import ConflictLayer from './layers/ConflictLayer';
import TrafficLayer from './layers/TrafficLayer';
import HeatmapLayer from './layers/HeatmapLayer';
import HtmlLayerSync from './HtmlLayerSync';
import { PointsLayerSync, ArcsLayerSync, RingsLayerSync } from './PointArcsRingsSync';
import { useGlobeStore } from '../../stores/globeStore';

// Auto-rotate speed (OrbitControls unit: full rotations per minute × 2)
// We want ~3 min/rotation → 0.33
const AUTO_ROTATE_SPEED = 0.33;
// Delay after the user stops interacting before rotation resumes (ms)
const RESUME_DELAY_MS = 2500;

export default function GlobeCanvas() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [globeInstance, setGlobeInstance] = useState<GlobeInstance | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const isAutoRotating = useGlobeStore((s) => s.isAutoRotating);
  const flyToTarget    = useGlobeStore((s) => s.flyToTarget);
  const clearFlyTo     = useGlobeStore((s) => s.clearFlyTo);
  const setCameraAltitude = useGlobeStore((s) => s.setCameraAltitude);
  // Ref so event handlers always see the latest store value without re-registering
  const isAutoRotatingRef = useRef(isAutoRotating);
  useEffect(() => { isAutoRotatingRef.current = isAutoRotating; }, [isAutoRotating]);
  const setCameraAltitudeRef = useRef(setCameraAltitude);
  useEffect(() => { setCameraAltitudeRef.current = setCameraAltitude; }, [setCameraAltitude]);

  // Ref to orbit controls so the store-sync effect can reach it
  const ctrlRef = useRef<ReturnType<InstanceType<typeof Globe>['controls']> | null>(null);
  const resumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── Instantiate Globe.GL ──────────────────────────────────────────────────
    let globe: GlobeInstance;
    try {
      globe = new Globe(container)
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
    ctrl.autoRotate = isAutoRotatingRef.current;
    ctrl.autoRotateSpeed = AUTO_ROTATE_SPEED;
    ctrl.enableDamping = true;
    ctrl.dampingFactor = 0.08;
    ctrlRef.current = ctrl;

    // ── Pause / resume on user interaction ────────────────────────────────────
    // Only resumes after drag if the store says rotation should be on.
    const pauseRotation = () => {
      ctrl.autoRotate = false;
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
    };

    const scheduleResume = () => {
      if (!isAutoRotatingRef.current) return; // play/pause button is off
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = setTimeout(() => {
        if (isAutoRotatingRef.current) ctrl.autoRotate = true;
      }, RESUME_DELAY_MS);
    };

    container.addEventListener('mousedown', pauseRotation);
    container.addEventListener('touchstart', pauseRotation, { passive: true });
    container.addEventListener('mouseup', scheduleResume);
    container.addEventListener('touchend', scheduleResume);

    // ── Camera altitude → LOD tracking ────────────────────────────────────────
    // Throttle: push altitude to the store at most once every 150 ms to avoid
    // thrashing Zustand on every OrbitControls 'change' event.
    let altThrottleTimer: ReturnType<typeof setTimeout> | null = null;
    const onCameraChange = () => {
      if (altThrottleTimer) return;
      altThrottleTimer = setTimeout(() => {
        altThrottleTimer = null;
        const pov = (globe as unknown as { pointOfView: () => { altitude: number } }).pointOfView();
        if (typeof pov?.altitude === 'number') {
          setCameraAltitudeRef.current(pov.altitude);
        }
      }, 150);
    };
    ctrl.addEventListener('change', onCameraChange);

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
    setGlobeInstance(() => globe);

    return () => {
      window.removeEventListener('resize', onResize);
      container.removeEventListener('mousedown', pauseRotation);
      container.removeEventListener('touchstart', pauseRotation);
      container.removeEventListener('mouseup', scheduleResume);
      container.removeEventListener('touchend', scheduleResume);
      ctrl.removeEventListener('change', onCameraChange);
      if (altThrottleTimer) clearTimeout(altThrottleTimer);
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      globe._destructor();
    };
  }, []); // only run once on mount

  // Sync store isAutoRotating → orbit controls (runs whenever the button is pressed)
  useEffect(() => {
    if (!ctrlRef.current) return;
    ctrlRef.current.autoRotate = isAutoRotating;
    if (!isAutoRotating && resumeTimerRef.current) {
      clearTimeout(resumeTimerRef.current);
    }
  }, [isAutoRotating]);

  // Fly camera to a location when flyToTarget changes
  useEffect(() => {
    if (!globeInstance || !flyToTarget) return;
    globeInstance.pointOfView(
      { lat: flyToTarget.lat, lng: flyToTarget.lng, altitude: flyToTarget.altitude ?? 1.5 },
      1200,
    );
    clearFlyTo();
  }, [flyToTarget, globeInstance, clearFlyTo]);

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
      {globeInstance && <NewsLayer />}
      {globeInstance && <DisasterLayer />}
      {globeInstance && <ShipLayer />}
      {globeInstance && <SatelliteLayer />}
      {globeInstance && <ConflictLayer />}
      {globeInstance && <TrafficLayer />}
      {/* Heatmap density overlay — replaces individual markers when active */}
      {globeInstance && <HeatmapLayer />}
      {/* Single component that owns globe.htmlElementsData(): merges news + disaster + ship */}
      {globeInstance && <HtmlLayerSync />}
      {/* Single components that own globe.pointsData/arcsData/ringsData slots */}
      {globeInstance && <PointsLayerSync />}
      {globeInstance && <ArcsLayerSync />}
      {globeInstance && <RingsLayerSync />}
    </GlobeContext.Provider>
  );
}

