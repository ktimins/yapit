import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthUser } from "@/hooks/useAuthUser";
import { authEnabled } from "@/auth";
import { getAnonymousToken, getOrCreateAnonymousId } from "@/lib/anonymousId";

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ||
	`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/api`;

export interface WSMessage {
  type: "status" | "evicted" | "error";
  [key: string]: unknown;
}

export interface UseTTSWebSocketReturn {
  isConnected: boolean;
  isReconnecting: boolean;
  connectionError: string | null;
  send: (msg: object) => void;
  checkConnected: () => boolean;
}

export function useTTSWebSocket(
  onMessage: (data: WSMessage) => void,
  onConnect?: () => void,
): UseTTSWebSocketReturn {
  const user = useAuthUser();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onConnectRef = useRef(onConnect);
  onConnectRef.current = onConnect;

  const BASE_RECONNECT_DELAY = 1000;
  const MAX_RECONNECT_DELAY = 30000;
  const MAX_AUTH_FAILURES = 3;

  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const isConnectedRef = useRef(false);
  const connectingRef = useRef(false);
  const epochRef = useRef(0);
  const authFailuresRef = useRef(0);

  // Message queue: messages sent while WS is not connected are queued and drained on connect
  const messageQueueRef = useRef<object[]>([]);

  const getWebSocketUrl = useCallback(async (): Promise<string> => {
    const baseUrl = `${WS_BASE_URL}/v1/ws/tts`;
    if (!authEnabled) return baseUrl;
    if (user?.currentSession) {
      // getTokens() refreshes the access token via the refresh token when expired.
      // A failure here is transient (e.g. mobile network after backgrounding) — throw
      // so connect() retries. Never downgrade a signed-in user to an anonymous identity.
      const { accessToken } = await user.currentSession.getTokens();
      if (!accessToken) throw new Error("No access token for signed-in session");
      return `${baseUrl}?token=${encodeURIComponent(accessToken)}`;
    }
    const anonymousId = await getOrCreateAnonymousId();
    const anonymousToken = getAnonymousToken();
    return `${baseUrl}?anonymous_id=${encodeURIComponent(anonymousId)}&anonymous_token=${encodeURIComponent(anonymousToken ?? "")}`;
  }, [user]);

  const connect = useCallback(async () => {
    // wsRef is set at creation, so non-null covers CONNECTING and OPEN;
    // connectingRef covers the async token fetch before the socket exists.
    if (connectingRef.current || wsRef.current) return;
    connectingRef.current = true;
    const epoch = epochRef.current;

    const scheduleReconnect = () => {
      setIsReconnecting(true);
      const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current), MAX_RECONNECT_DELAY);
      console.log(`[TTS WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`);
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectAttemptsRef.current++;
        connect();
      }, delay);
    };

    try {
      const url = await getWebSocketUrl();
      if (epoch !== epochRef.current) {
        // Unmounted or user changed while fetching the token — abandon this attempt
        connectingRef.current = false;
        return;
      }
      console.log("[TTS WS] Connecting to:", url.replace(/token=[^&]+/, "token=***"));
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        connectingRef.current = false;
        console.log("[TTS WS] Connected");
        isConnectedRef.current = true;
        setIsConnected(true);
        setIsReconnecting(false);
        setConnectionError(null);

        // Drain queued messages
        const queue = messageQueueRef.current;
        if (queue.length > 0) {
          console.log(`[TTS WS] Draining ${queue.length} queued messages`);
          for (const msg of queue) {
            ws.send(JSON.stringify(msg));
          }
          messageQueueRef.current = [];
        }

        // Notify listeners (synthesizer uses this to retry pending blocks)
        onConnectRef.current?.();

        reconnectAttemptsRef.current = 0;
        authFailuresRef.current = 0;
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data: WSMessage = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch (err) {
          console.error("[TTS WS] Failed to parse message:", err);
        }
      };

      ws.onerror = (event) => {
        console.error("[TTS WS] Error:", event);
      };

      ws.onclose = (event) => {
        connectingRef.current = false;
        console.log("[TTS WS] Disconnected:", event.code, event.reason);
        isConnectedRef.current = false;
        setIsConnected(false);
        if (wsRef.current === ws) wsRef.current = null;

        if (event.code === 1000) return;

        if (event.code === 1008) {
          // Auth rejection is usually a stale access token — each reconnect fetches a
          // fresh one via getTokens(). Only give up after repeated failures (dead session).
          authFailuresRef.current++;
          if (authFailuresRef.current >= MAX_AUTH_FAILURES) {
            setIsReconnecting(false);
            setConnectionError("Authentication failed. Please log in again.");
            return;
          }
        }

        scheduleReconnect();
      };
    } catch (err) {
      connectingRef.current = false;
      console.error("[TTS WS] Failed to connect:", err);
      scheduleReconnect();
    }
  }, [getWebSocketUrl]);

  useEffect(() => {
    connect();
    return () => {
      epochRef.current++;
      connectingRef.current = false;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      isConnectedRef.current = false;
      setIsConnected(false);
    };
  }, [connect]);

  // Mobile resume: when the app returns to the foreground (or network comes back),
  // the backoff timer may be up to 30s out — or we gave up after auth failures.
  // Reset and reconnect immediately so pause→play after unlock is seamless.
  useEffect(() => {
    const wake = () => {
      if (connectingRef.current || wsRef.current) return;
      reconnectAttemptsRef.current = 0;
      authFailuresRef.current = 0;
      setConnectionError(null);
      setIsReconnecting(false);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      connect();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") wake();
    };
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [connect]);

  const send = useCallback((msg: object) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      messageQueueRef.current.push(msg);
      return;
    }
    wsRef.current.send(JSON.stringify(msg));
  }, []);

  const checkConnected = useCallback(() => isConnectedRef.current, []);

  return {
    isConnected,
    isReconnecting,
    connectionError,
    send,
    checkConnected,
  };
}
