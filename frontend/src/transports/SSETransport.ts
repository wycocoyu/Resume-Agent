/**
 * SSETransport - Server-Sent Events transport layer
 *
 * Replaces WebSocket with HTTP + SSE for:
 * - Better connection stability
 * - Automatic reconnection handling
 * - Simpler architecture
 * - Heartbeat detection
 */
import { getApiBaseUrl, isAgentEnabled } from '@/lib/runtimeEnv';
import { getAuthHeaders } from '@/lib/authHeaders';

export interface SSEEvent {
  id: string;
  type: string;
  data: any;
  timestamp: string;
}

export interface SSEConfig {
  baseUrl: string;
  heartbeatTimeout?: number;  // milliseconds, default 60000 (60s)
  autoReconnect?: boolean;
  maxReconnectAttempts?: number;
  reconnectDelay?: number; // milliseconds
  onMessage?: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

type EventCallback = (event: SSEEvent) => void;
type ErrorCallback = (error: Error) => void;

export class SSETransport {
  private config: SSEConfig;
  private abortController: AbortController | null = null;
  private lastHeartbeatTime: number = Date.now();
  private heartbeatCheckInterval: NodeJS.Timeout | null = null;
  private isConnected: boolean = false;
  private conversationId: string | null = null;
  private lastEventId: string | null = null;
  private lastPrompt: string | null = null;
  private lastResumePath: string | undefined;
  private resumeData: any = null;
  private reconnectAttempts: number = 0;
  private reconnectTimer: NodeJS.Timeout | null = null;

  // Event listeners
  private messageListeners: EventCallback[] = [];
  private errorListeners: ErrorCallback[] = [];

  constructor(config: SSEConfig) {
    this.config = {
      heartbeatTimeout: 60000,  // 60 seconds default
      autoReconnect: true,
      maxReconnectAttempts: 5,
      reconnectDelay: 1000,
      ...config,
    };
  }

  /**
   * Send a message and start receiving SSE stream
   */
  async send(prompt: string, resumePath?: string, resumeData?: any): Promise<void> {
    if (!isAgentEnabled()) {
      const error = new Error('Agent is disabled by VITE_AGENT_ENABLED');
      this.emitError(error);
      this.config.onError?.(error);
      return;
    }

    // Abort any existing connection
    this.disconnect();

    // Create new abort controller
    this.abortController = new AbortController();

    // Start heartbeat monitoring
    this.startHeartbeatCheck();

    this.lastPrompt = prompt;
    this.lastResumePath = resumePath;
    if (resumeData !== undefined) {
      this.resumeData = resumeData;
    }

    const url = `${this.config.baseUrl}/api/agent/stream`;
    console.log('[SSETransport] Connecting to', url);

    // 构建请求体，确保 resume_data 要么是对象，要么是 null（而不是 undefined）
    const requestBody: any = {
      message: prompt,
      conversation_id: this.conversationId || null,
    };
    // 只有当 resumeData 不为 undefined 时才添加 resume_data 字段
    if (this.resumeData !== undefined) {
      requestBody.resume_data = this.resumeData;
    }

    // 2026-07-17 身份统一：JWT 下架，认证走 BetterAuth cookie（fetch 已被
    // configureAuthWebRequests patch 自动带 credentials），不再注入 Bearer。
    const authHeaders = getAuthHeaders();

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...authHeaders,
        },
        credentials: 'include',
        body: JSON.stringify(requestBody),
        signal: this.abortController.signal,
      });

      if (!response.ok) {
        let detail = '';
        try {
          const bodyText = await response.text();
          if (bodyText) {
            try {
              const parsed = JSON.parse(bodyText);
              detail = parsed?.message || parsed?.detail || bodyText;
            } catch {
              detail = bodyText;
            }
          }
        } catch {
          // ignore body parse errors
        }
        const suffix = detail ? ` - ${String(detail).slice(0, 300)}` : '';
        throw new Error(`SSE connection failed: ${response.status} ${response.statusText}${suffix}`);
      }

      if (!response.body) {
        throw new Error('Response body is null');
      }

      this.isConnected = true;
      this.lastHeartbeatTime = Date.now();
      this.reconnectAttempts = 0;
      this.config.onConnect?.();
      console.log('[SSETransport] Connected');

      // Parse SSE stream
      await this.parseSSEStream(response.body);

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('[SSETransport] Connection aborted');
      } else {
        console.error('[SSETransport] Connection error:', error);
        this.emitError(error instanceof Error ? error : new Error(String(error)));
        this.scheduleReconnect();
      }
    } finally {
      this.isConnected = false;
      this.stopHeartbeatCheck();
      this.config.onDisconnect?.();
    }
  }

  /**
   * Parse SSE stream from ReadableStream
   */
  private async parseSSEStream(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let chunkCount = 0;

    try {
      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          console.log('[SSETransport] Stream ended, total chunks:', chunkCount);
          break;
        }

        chunkCount++;
        const decoded = decoder.decode(value, { stream: true });
        buffer += decoded;
        
        if (chunkCount <= 3) {
          console.log(`[SSETransport] Chunk ${chunkCount} received:`, decoded.substring(0, 200));
        }

        // Process complete events in buffer
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';  // Keep incomplete data in buffer

        for (const eventText of lines) {
          if (eventText.trim()) {
            console.log('[SSETransport] Processing event:', eventText.substring(0, 200));
            this.processSSEEvent(eventText);
          }
        }
      }

      // Process any remaining data
      if (buffer.trim()) {
        console.log('[SSETransport] Processing remaining buffer:', buffer.substring(0, 200));
        this.processSSEEvent(buffer);
      }

    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('[SSETransport] Stream reading aborted');
      } else {
        throw error;
      }
    }
  }

  /**
   * Process a single SSE event
   */
  private processSSEEvent(eventText: string): void {
    try {
      // Parse SSE format: "id: xxx\ndata: {...}" or "event: xxx\ndata: {...}"
      const lines = eventText.split('\n');
      let eventId = '';
      let eventType = '';
      let eventData = '';

      for (const line of lines) {
        if (line.startsWith('id: ')) {
          eventId = line.slice(4).trim();
        } else if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          eventData = line.slice(6);
        }
      }

      if (!eventData) {
        console.log('[SSETransport] No data in event:', eventText.substring(0, 100));
        return;
      }

      const parsed = JSON.parse(eventData);
      console.log('[SSETransport] Parsed event:', { type: eventType || parsed.type, id: eventId || parsed.id, dataType: typeof parsed.data });

      // Update heartbeat time
      this.lastHeartbeatTime = Date.now();

      // Extract conversation_id if present
      if (parsed.data?.conversation_id && !this.conversationId) {
        this.conversationId = parsed.data.conversation_id;
      }
      if (eventId) {
        this.lastEventId = eventId;
      } else if (parsed.id) {
        this.lastEventId = parsed.id;
      }

      // Convert to SSEEvent format
      const event: SSEEvent = {
        id: eventId || parsed.id,
        type: parsed.type,
        data: parsed.data,
        timestamp: parsed.timestamp,
      };

      // Handle heartbeat internally
      if (event.type === 'heartbeat') {
        console.log('[SSETransport] Heartbeat received');
        return;
      }

      // Emit to listeners
      this.emitMessage(event);
      this.config.onMessage?.(event);

    } catch (error) {
      console.error('[SSETransport] Failed to parse event:', eventText, error);
    }
  }

  /**
   * Start heartbeat monitoring
   */
  private startHeartbeatCheck(): void {
    this.stopHeartbeatCheck();

    this.heartbeatCheckInterval = setInterval(() => {
      const now = Date.now();
      const timeout = this.config.heartbeatTimeout || 60000;

      if (this.isConnected && now - this.lastHeartbeatTime > timeout) {
        console.warn('[SSETransport] Heartbeat timeout, connection may be dead');
        this.emitError(new Error('Heartbeat timeout'));
        this.scheduleReconnect();
      }
    }, 10000);  // Check every 10 seconds
  }

  /**
   * Stop heartbeat monitoring
   */
  private stopHeartbeatCheck(): void {
    if (this.heartbeatCheckInterval) {
      clearInterval(this.heartbeatCheckInterval);
      this.heartbeatCheckInterval = null;
    }
  }

  /**
   * Disconnect current stream
   */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.stopHeartbeatCheck();
    this.isConnected = false;
    console.log('[SSETransport] Disconnected');
  }

  /**
   * Check if connected
   */
  get connected(): boolean {
    return this.isConnected;
  }

  /**
   * Get current conversation ID
   */
  getConversationId(): string | null {
    return this.conversationId;
  }

  /**
   * Set conversation ID for continuing a conversation
   */
  setConversationId(id: string | null): void {
    this.conversationId = id;
  }

  setResumeData(data: any): void {
    this.resumeData = data;
  }

  /**
   * Clear conversation (start fresh)
   */
  clearConversation(): void {
    this.conversationId = null;
    this.lastEventId = null;
    this.reconnectAttempts = 0;
  }

  // ============================================================================
  // Event Emitter Methods
  // ============================================================================

  /**
   * Add message listener
   */
  onMessage(callback: EventCallback): () => void {
    this.messageListeners.push(callback);
    return () => {
      this.messageListeners = this.messageListeners.filter(cb => cb !== callback);
    };
  }

  /**
   * Add error listener
   */
  onError(callback: ErrorCallback): () => void {
    this.errorListeners.push(callback);
    return () => {
      this.errorListeners = this.errorListeners.filter(cb => cb !== callback);
    };
  }

  private emitMessage(event: SSEEvent): void {
    for (const listener of this.messageListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('[SSETransport] Error in message listener:', error);
      }
    }
  }

  private emitError(error: Error): void {
    for (const listener of this.errorListeners) {
      try {
        listener(error);
      } catch (e) {
        console.error('[SSETransport] Error in error listener:', e);
      }
    }
    this.config.onError?.(error);
  }

  private scheduleReconnect(): void {
    if (!this.config.autoReconnect) return;
    if (!this.lastPrompt) return;
    if (this.reconnectAttempts >= (this.config.maxReconnectAttempts || 5)) {
      return;
    }
    if (this.reconnectTimer) return;

    const baseDelay = this.config.reconnectDelay || 1000;
    const delay = Math.min(baseDelay * Math.pow(2, this.reconnectAttempts), 10000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.send(this.lastPrompt || "", this.lastResumePath).catch(() => null);
    }, delay);
  }
}

// ============================================================================
// Default instance factory
// ============================================================================

/**
 * Create SSE transport with default configuration
 */
export function createSSETransport(config?: Partial<SSEConfig>): SSETransport {
  return new SSETransport({
    baseUrl: getApiBaseUrl(),
    heartbeatTimeout: 60000,
    ...config,
  });
}
