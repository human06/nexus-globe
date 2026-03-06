/**
 * useWebSocket — manages the persistent WS connection to the backend.
 *
 * Responsibilities:
 *  - Connects to ws://localhost:8000/ws on mount
 *  - Exponential-backoff reconnect (1 → 2 → 4 → 8 → 16 → 30 s)
 *  - Sends subscribe/unsubscribe in sync with the active layers in the store
 *  - Normalises server event format → GlobeEvent and feeds it into the store
 *  - Exposes status, subscribe, unsubscribe, requestDetail
 */
import { useEffect, useRef, useCallback } from 'react';
import { useGlobeStore } from '../stores/globeStore';
import type { GlobeEvent, WSIncomingMessage } from '../types/events';

// ── Constants ─────────────────────────────────────────────────────────────────

const WS_URL = 'ws://localhost:8000/ws';
const BACKOFF_STEPS_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];

// ── Server → Frontend normalisation ──────────────────────────────────────────

/**
 * The backend serialises events using Python/SQLAlchemy naming (snake_case,
 * with field-name differences).  Transform to the camelCase GlobeEvent shape.
 */
function normalizeServerEvent(raw: Record<string, unknown>): GlobeEvent {
  const expiresAtRaw = raw['expires_at'] as string | null | undefined;
  const createdAtRaw = (raw['created_at'] ?? raw['timestamp']) as string | number | null | undefined;
  return {
    id:          String(raw['id'] ?? raw['event_id'] ?? ''),
    type:        (raw['event_type'] ?? raw['type']) as GlobeEvent['type'],
    category:    String(raw['category'] ?? ''),
    title:       String(raw['title'] ?? ''),
    description: String(raw['description'] ?? ''),
    latitude:    Number(raw['latitude'] ?? raw['lat'] ?? 0),
    longitude:   Number(raw['longitude'] ?? raw['lng'] ?? raw['lon'] ?? 0),
    altitude:    raw['altitude_m'] != null ? Number(raw['altitude_m']) : raw['altitude'] != null ? Number(raw['altitude']) : undefined,
    heading:     raw['heading_deg'] != null ? Number(raw['heading_deg']) : raw['heading'] != null ? Number(raw['heading']) : undefined,
    speed:       raw['speed_kmh'] != null ? Number(raw['speed_kmh']) : raw['speed'] != null ? Number(raw['speed']) : undefined,
    severity:    (Number(raw['severity'] ?? 1)) as GlobeEvent['severity'],
    source:      String(raw['source'] ?? ''),
    sourceUrl:   raw['source_url'] != null ? String(raw['source_url']) : undefined,
    timestamp:   createdAtRaw
      ? typeof createdAtRaw === 'number'
        ? createdAtRaw
        : new Date(createdAtRaw).getTime()
      : Date.now(),
    expiresAt:   expiresAtRaw ? new Date(expiresAtRaw).getTime() : undefined,
    metadata:    (raw['metadata'] as Record<string, unknown>) ?? {},
    trail:       (raw['trail'] as GlobeEvent['trail']) ?? undefined,
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface UseWebSocketReturn {
  /** Subscribe to additional layers (sends subscribe action) */
  subscribe: (layers: string[]) => void;
  /** Unsubscribe from layers */
  unsubscribe: (layers: string[]) => void;
  /** Request full detail for a specific event */
  requestDetail: (eventId: string) => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const wsRef             = useRef<WebSocket | null>(null);
  const backoffIdxRef     = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef        = useRef(true);
  /** Layers we have already subscribed to this session */
  const subscribedRef     = useRef<Set<string>>(new Set());

  // Reactive layers state — triggers the layer-sync effect on toggle
  const layers = useGlobeStore((s) => s.layers);

  // ── Helpers ──────────────────────────────────────────────────────────────

  const send = useCallback((payload: unknown) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }, []);

  const subscribeToLayers = useCallback((layerList: string[]) => {
    const unsent = layerList.filter((l) => !subscribedRef.current.has(l));
    if (unsent.length === 0) return;
    send({ action: 'subscribe', layers: unsent });
    unsent.forEach((l) => subscribedRef.current.add(l));
  }, [send]);

  const unsubscribeFromLayers = useCallback((layerList: string[]) => {
    send({ action: 'unsubscribe', layers: layerList });
    layerList.forEach((l) => subscribedRef.current.delete(l));
  }, [send]);

  const requestDetail = useCallback((eventId: string) => {
    send({ action: 'get_detail', event_id: eventId });
  }, [send]);

  // ── Message handler ───────────────────────────────────────────────────────

  const handleMessage = useCallback((event: MessageEvent) => {
    let msg: WSIncomingMessage;
    try {
      msg = JSON.parse(event.data as string) as WSIncomingMessage;
    } catch {
      console.warn('[useWebSocket] malformed message:', event.data);
      return;
    }

    const store = useGlobeStore.getState();

    switch (msg.type) {
      case 'snapshot': {
        const raw = msg.data as Record<string, unknown>[];
        if (Array.isArray(raw)) {
          store.upsertEvents(raw.map(normalizeServerEvent));
        }
        break;
      }
      case 'event_update': {
        const ev = normalizeServerEvent(msg.data as Record<string, unknown>);
        store.upsertEvents([ev]);
        break;
      }
      case 'event_batch': {
        const raw = msg.data as Record<string, unknown>[];
        if (Array.isArray(raw)) {
          store.upsertEvents(raw.map(normalizeServerEvent));
        }
        break;
      }
      case 'event_remove': {
        const { id } = msg.data as { id: string };
        store.removeEvent(id);
        break;
      }
      case 'ping':
        // Heartbeat — no-op on client
        break;
      case 'error':
        console.warn('[useWebSocket] server error:', (msg as { type: 'error'; data: { message: string } }).data.message);
        break;
    }
  }, []);

  // ── Connection lifecycle ──────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    useGlobeStore.getState().setWsStatus('connecting');
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      backoffIdxRef.current = 0;
      useGlobeStore.getState().setWsStatus('connected');
      subscribedRef.current.clear(); // Reset so we re-subscribe fresh

      // Subscribe to all active layers
      const currentLayers = useGlobeStore.getState().layers;
      const activeLayers = (Object.entries(currentLayers) as [string, boolean][])
        .filter(([, on]) => on)
        .map(([type]) => {
          // Map store key → backend event_type key
          // 'flights' → 'flight', 'ships' → 'ship', 'satellites' → 'satellite'
          // 'disasters' → 'disaster', 'conflicts' → 'conflict', 'cameras' → 'camera'
          return type.replace(/s$/, '').replace(/ie$/, 'y');
        });
      subscribeToLayers(activeLayers);
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      if (!mountedRef.current) return;
      useGlobeStore.getState().setWsStatus('disconnected');
      wsRef.current = null;
      subscribedRef.current.clear();
      // Schedule reconnect with backoff
      const delay = BACKOFF_STEPS_MS[Math.min(backoffIdxRef.current, BACKOFF_STEPS_MS.length - 1)];
      backoffIdxRef.current = Math.min(backoffIdxRef.current + 1, BACKOFF_STEPS_MS.length - 1);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = (err) => {
      console.error('[useWebSocket] error:', err);
      // onclose will fire after onerror — reconnect handled there
    };
  }, [handleMessage, subscribeToLayers]);

  // ── Mount / unmount ───────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on intentional close
        wsRef.current.close();
      }
      useGlobeStore.getState().setWsStatus('disconnected');
    };
  }, [connect]);

  // ── React to layer toggle changes ─────────────────────────────────────────

  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    // Map store layer keys to backend event_type names
    const toBackendType = (key: string) =>
      key.replace(/s$/, '').replace(/ie$/, 'y');

    (Object.entries(layers) as [string, boolean][]).forEach(([key, on]) => {
      const backendType = toBackendType(key);
      if (on && !subscribedRef.current.has(backendType)) {
        subscribeToLayers([backendType]);
      } else if (!on && subscribedRef.current.has(backendType)) {
        unsubscribeFromLayers([backendType]);
      }
    });
  }, [layers, subscribeToLayers, unsubscribeFromLayers]);

  return {
    subscribe: subscribeToLayers,
    unsubscribe: unsubscribeFromLayers,
    requestDetail,
  };
}

