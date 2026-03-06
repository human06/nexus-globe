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
