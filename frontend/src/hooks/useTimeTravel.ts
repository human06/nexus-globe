/**
 * useTimeTravel — manages historical vs live mode for the timeline scrubber.
 *
 * Story 3.11:
 * - Exposes enterHistorical(timestamp) / returnToLive()
 * - Fetches /api/events/history?timestamp=T and feeds results into the store
 * - Manages playback: speed multiplier, requestAnimationFrame loop
 * - Keyboard shortcuts: Space (play/pause), ← → (±1h), L (live)
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useGlobeStore } from '../stores/globeStore';
import type { GlobeEvent } from '../types/events';

export type PlaybackSpeed = 1 | 10 | 60 | 360;

interface HistorySnapshot {
  events: GlobeEvent[];
  snapshotTime: number;
}

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

async function fetchSnapshot(timestamp: number): Promise<HistorySnapshot | null> {
  try {
    const iso = new Date(timestamp).toISOString();
    const res = await fetch(`/api/events/history?timestamp=${encodeURIComponent(iso)}`);
    if (!res.ok) return null;
    const data = await res.json() as { events?: GlobeEvent[]; snapshot_time?: string };
    return {
      events: (data.events ?? []) as GlobeEvent[],
      snapshotTime: data.snapshot_time ? new Date(data.snapshot_time).getTime() : timestamp,
    };
  } catch {
    return null;
  }
}

export function useTimeTravel() {
  const setTimeMode       = useGlobeStore((s) => s.setTimeMode);
  const setCurrentViewTime = useGlobeStore((s) => s.setCurrentViewTime);
  const timeMode          = useGlobeStore((s) => s.timeMode);
  const currentViewTime   = useGlobeStore((s) => s.currentViewTime);
  const upsertEvents      = useGlobeStore((s) => s.upsertEvents);

  const [isPlaying, setIsPlaying]           = useState(false);
  const [playbackSpeed, setPlaybackSpeed]   = useState<PlaybackSpeed>(60);
  const [isFetching, setIsFetching]         = useState(false);

  const rafRef       = useRef<number | null>(null);
  const lastTickRef  = useRef<number>(0);
  const viewTimeRef  = useRef<number>(currentViewTime);

  // Keep ref in sync with store value
  viewTimeRef.current = currentViewTime;

  // ── Scrub to a specific historical timestamp ────────────────────────────
  const scrubTo = useCallback(async (timestamp: number) => {
    const clamped = Math.max(Date.now() - SEVEN_DAYS_MS, Math.min(Date.now(), timestamp));
    setCurrentViewTime(clamped);
    setTimeMode('historical');
    setIsFetching(true);
    const snap = await fetchSnapshot(clamped);
    setIsFetching(false);
    if (snap) {
      upsertEvents(snap.events);
    }
  }, [setCurrentViewTime, setTimeMode, upsertEvents]);

  // ── Return to live ──────────────────────────────────────────────────────
  const returnToLive = useCallback(() => {
    setIsPlaying(false);
    setTimeMode('live');
    setCurrentViewTime(Date.now());
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, [setTimeMode, setCurrentViewTime]);

  // ── Playback RAF loop ───────────────────────────────────────────────────
  const tick = useCallback((now: number) => {
    if (lastTickRef.current === 0) {
      lastTickRef.current = now;
    }
    const wallDelta = now - lastTickRef.current;
    lastTickRef.current = now;

    // Advance view time by speed multiplier
    const newTime = viewTimeRef.current + wallDelta * playbackSpeed;

    if (newTime >= Date.now()) {
      // Reached "now" → snap to live
      returnToLive();
      return;
    }

    viewTimeRef.current = newTime;
    setCurrentViewTime(newTime);

    // Fetch snapshot periodically (every 15 min of simulated time)
    // We use a debounce approach — only fetch when we cross a 15min boundary
    const prev15 = Math.floor((newTime - wallDelta * playbackSpeed) / (15 * 60 * 1000));
    const curr15 = Math.floor(newTime / (15 * 60 * 1000));
    if (curr15 !== prev15) {
      fetchSnapshot(newTime).then((snap) => {
        if (snap) upsertEvents(snap.events);
      });
    }

    rafRef.current = requestAnimationFrame(tick);
  }, [playbackSpeed, returnToLive, setCurrentViewTime, upsertEvents]);

  const togglePlay = useCallback(() => {
    if (timeMode === 'live') {
      // Enter historical at "now - 1s" to begin playback
      void scrubTo(Date.now() - 1000);
    }
    setIsPlaying((prev) => {
      const next = !prev;
      if (next) {
        lastTickRef.current = 0;
        rafRef.current = requestAnimationFrame(tick);
      } else {
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
      }
      return next;
    });
  }, [timeMode, scrubTo, tick]);

  // Restart RAF when speed changes while playing
  useEffect(() => {
    if (isPlaying) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
      lastTickRef.current = 0;
      rafRef.current = requestAnimationFrame(tick);
    }
  }, [playbackSpeed]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ── Keyboard shortcuts ──────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return;
      switch (e.key) {
        case ' ':
          e.preventDefault();
          togglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          void scrubTo(viewTimeRef.current - 60 * 60 * 1000);
          break;
        case 'ArrowRight':
          e.preventDefault();
          void scrubTo(viewTimeRef.current + 60 * 60 * 1000);
          break;
        case 'l':
        case 'L':
          e.preventDefault();
          returnToLive();
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePlay, scrubTo, returnToLive]);

  return {
    timeMode,
    currentViewTime,
    isPlaying,
    playbackSpeed,
    isFetching,
    setPlaybackSpeed,
    scrubTo,
    returnToLive,
    togglePlay,
    minTime: Date.now() - SEVEN_DAYS_MS,
    maxTime: Date.now(),
  };
}
