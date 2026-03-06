export type EventType =
  | 'news'
  | 'flight'
  | 'ship'
  | 'satellite'
  | 'disaster'
  | 'conflict'
  | 'traffic'
  | 'camera';

export interface GlobeEvent {
  id: string;
  type: EventType;
  category: string;
  title: string;
  description: string;
  latitude: number;
  longitude: number;
  altitude?: number;
  heading?: number;
  speed?: number;
  /** Severity level 1 (low) to 5 (critical) */
  severity: 1 | 2 | 3 | 4 | 5;
  source: string;
  sourceUrl?: string;
  timestamp: number; // Unix ms
  expiresAt?: number; // Unix ms
  metadata: Record<string, unknown>;
  trail?: Array<{ lat: number; lng: number; alt?: number; ts: number }>;
}

export interface LayerConfig {
  type: EventType;
  label: string;
  color: string;
  icon: string;
  visible: boolean;
}

// ── WebSocket message types ────────────────────────────────────────────────────

export type WSStatus = 'connected' | 'connecting' | 'disconnected';

/**
 * Message types pushed from the backend WebSocket server.
 */
export type WSMessageType =
  | 'snapshot'      // Initial batch of events for a layer
  | 'event_update'  // Single event upsert
  | 'event_batch'   // Multiple events upsert
  | 'event_remove'  // An event expired / was deleted
  | 'ping'          // Heartbeat from server
  | 'error';        // Server-side error

export interface WSSnapshot {
  type: 'snapshot';
  data: GlobeEvent[];
}

export interface WSEventUpdate {
  type: 'event_update';
  data: GlobeEvent;
}

export interface WSEventBatch {
  type: 'event_batch';
  data: GlobeEvent[];
}

export interface WSEventRemove {
  type: 'event_remove';
  data: { id: string };
}

export interface WSPing {
  type: 'ping';
}

export interface WSError {
  type: 'error';
  data: { message: string };
}

export type WSIncomingMessage =
  | WSSnapshot
  | WSEventUpdate
  | WSEventBatch
  | WSEventRemove
  | WSPing
  | WSError;

// ── Client → Server message types ─────────────────────────────────────────────

export interface WSSubscribeAction {
  action: 'subscribe';
  layers: string[];
}

export interface WSUnsubscribeAction {
  action: 'unsubscribe';
  layers: string[];
}

export interface WSGetDetailAction {
  action: 'get_detail';
  event_id: string;
}

export type WSOutgoingMessage =
  | WSSubscribeAction
  | WSUnsubscribeAction
  | WSGetDetailAction;

