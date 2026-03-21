/**
 * WebSocket manager — auto-reconnect, typed events, React-friendly.
 */

type EventHandler = (payload: unknown) => void;

export class DashboardWS {
    private ws: WebSocket | null = null;
    private handlers: Map<string, Set<EventHandler>> = new Map();
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectDelay = 1000;

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${protocol}://${window.location.host}/ws`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.reconnectDelay = 1000;
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                const handlers = this.handlers.get(msg.type);
                if (handlers) {
                    handlers.forEach(fn => fn(msg.payload));
                }
            } catch { /* ignore invalid JSON */ }
        };

        this.ws.onclose = () => {
            this._scheduleReconnect();
        };

        this.ws.onerror = () => {
            this.ws?.close();
        };
    }

    on(event: string, handler: EventHandler) {
        if (!this.handlers.has(event)) {
            this.handlers.set(event, new Set());
        }
        this.handlers.get(event)!.add(handler);
        return () => { this.handlers.get(event)?.delete(handler); };
    }

    send(type: string, payload: unknown) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, payload }));
        }
    }

    disconnect() {
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.ws?.close();
        this.ws = null;
    }

    private _scheduleReconnect() {
        this.reconnectTimer = setTimeout(() => {
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
            this.connect();
        }, this.reconnectDelay);
    }
}

export const dashboardWS = new DashboardWS();
