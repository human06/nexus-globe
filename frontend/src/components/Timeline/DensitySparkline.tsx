/**
 * DensitySparkline — tiny event-density bar chart above the timeline scrubber.
 *
 * Story 3.11: Fetches /api/events/history/range for the full 7-day window and
 * renders a filled area sparkline showing event count per hour bucket.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

interface Bucket {
  time: number;   // epoch ms
  count: number;
}

interface RangeBucket {
  bucket_start: string;
  event_count: number;
}

interface DensitySparklineProps {
  /** Unix ms — left edge of the visible range */
  minTime: number;
  /** Unix ms — right edge of the visible range */
  maxTime: number;
  /** Current handle position (used to draw a thin vertical cursor line) */
  currentTime: number;
  width: number;
  height?: number;
}

const FETCH_INTERVAL_MS = 5 * 60 * 1000; // re-fetch every 5 min

export default function DensitySparkline({
  minTime,
  maxTime,
  currentTime,
  width,
  height = 24,
}: DensitySparklineProps) {
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const cacheRef = useRef<{ fetched: number; data: Bucket[] }>({ fetched: 0, data: [] });

  useEffect(() => {
    const fetchData = async () => {
      if (Date.now() - cacheRef.current.fetched < FETCH_INTERVAL_MS && cacheRef.current.data.length) {
        setBuckets(cacheRef.current.data);
        return;
      }
      try {
        const start = new Date(minTime).toISOString();
        const end = new Date(maxTime).toISOString();
        const res = await fetch(
          `/api/events/history/range?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&interval=1h`,
        );
        if (!res.ok) return;
        const data = await res.json() as { buckets?: RangeBucket[] };
        const parsed: Bucket[] = (data.buckets ?? []).map((b) => ({
          time: new Date(b.bucket_start).getTime(),
          count: b.event_count,
        }));
        cacheRef.current = { fetched: Date.now(), data: parsed };
        setBuckets(parsed);
      } catch {
        // ignore — sparkline is decorative
      }
    };
    void fetchData();
  }, [minTime, maxTime]);

  const { points, cursorX } = useMemo(() => {
    if (!buckets.length || width <= 0) return { points: '', cursorX: null };

    const maxCount = Math.max(1, ...buckets.map((b) => b.count));
    const span = maxTime - minTime;

    const toX = (t: number) => ((t - minTime) / span) * width;
    const toY = (c: number) => height - (c / maxCount) * (height - 2);

    const pts = buckets.map((b) => `${toX(b.time).toFixed(1)},${toY(b.count).toFixed(1)}`).join(' ');
    // Close the polygon along the bottom
    const first = buckets[0];
    const last = buckets[buckets.length - 1];
    const closed = `${toX(first.time).toFixed(1)},${height} ${pts} ${toX(last.time).toFixed(1)},${height}`;

    const cx = toX(currentTime);

    return { points: closed, cursorX: cx };
  }, [buckets, width, height, minTime, maxTime, currentTime]);

  if (!buckets.length) return null;

  return (
    <svg
      width={width}
      height={height}
      style={{ display: 'block', overflow: 'visible' }}
      aria-hidden="true"
    >
      {/* Filled area */}
      <polygon
        points={points}
        fill="rgba(0,240,255,0.15)"
        stroke="rgba(0,240,255,0.4)"
        strokeWidth={0.8}
      />
      {/* Current-time cursor */}
      {cursorX !== null && (
        <line
          x1={cursorX}
          x2={cursorX}
          y1={0}
          y2={height}
          stroke="rgba(0,240,255,0.8)"
          strokeWidth={1.5}
        />
      )}
    </svg>
  );
}
