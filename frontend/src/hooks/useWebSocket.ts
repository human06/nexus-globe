import { useEffect, useRef, useCallback } from 'react';

type MessageHandler = (data: unknown) => void;

interface UseWebSocketOptions {
  url: string;
  onMessage?: MessageHandler;
  reconnectIntervalMs?: number;
}

/**
 * TODO: Implement WebSocket connection with auto-reconnect.
 * Connects to the backend /ws endpoint and dispatches messages
 * to the globe store.
 */
export function useWebSocket({
  url,
  onMessage,
  reconnectIntervalMs = 3000,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    // TODO: implement WebSocket handshake and subscription
    console.log('[useWebSocket] connecting to', url, reconnectIntervalMs);
  }, [url, reconnectIntervalMs]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  const send = useCallback((payload: unknown) => {
    // TODO: send JSON payload over open socket
    console.log('[useWebSocket] send', payload);
  }, []);

  return { send, onMessage };
}
