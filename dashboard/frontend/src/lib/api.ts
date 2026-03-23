/**
 * API client — wraps fetch with JWT auth, error handling, and type safety.
 */

const API_BASE = '/api';

let accessToken: string | null = localStorage.getItem('access_token');
let refreshToken: string | null = localStorage.getItem('refresh_token');

export function setTokens(access: string, refresh: string) {
    accessToken = access;
    refreshToken = refresh;
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
}

export function clearTokens() {
    accessToken = null;
    refreshToken = null;
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_role');
}

export function getRole(): string | null {
    return localStorage.getItem('user_role');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> || {}),
    };
    if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`;
    }

    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

    if (res.status === 401 && refreshToken) {
        // Try refresh
        const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (refreshRes.ok) {
            const data = await refreshRes.json();
            setTokens(data.access_token, refreshToken!);
            headers['Authorization'] = `Bearer ${data.access_token}`;
            const retry = await fetch(`${API_BASE}${path}`, { ...options, headers });
            if (!retry.ok) throw new ApiError(retry.status, await retry.text());
            return retry.json();
        }
        clearTokens();
        window.location.href = '/login';
        throw new ApiError(401, 'Session expired');
    }

    if (!res.ok) {
        const body = await res.text();
        throw new ApiError(res.status, body);
    }
    return res.json();
}

export class ApiError extends Error {
    status: number;
    body: string;
    constructor(status: number, body: string) {
        super(`API Error ${status}: ${body}`);
        this.status = status;
        this.body = body;
    }
}

// =================== Auth ===================
export const auth = {
    login: (username: string, password: string) =>
        request<{ access_token: string; refresh_token: string; role: string; expires_in: number }>(
            '/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }
        ),
    me: () => request<{ user_id: string; role: string }>('/auth/me'),
};

// =================== Config ===================
export const config = {
    get: () => request<{ yaml: string; etag: string }>('/config'),
    validate: (yaml: string) =>
        request<{ valid: boolean; errors: Array<{ line: number; col: number; msg: string }>; warnings: Array<{ line: number; col: number; msg: string }> }>(
            '/config/validate', { method: 'POST', body: JSON.stringify({ yaml }) }
        ),
    save: (yaml: string, etag: string) =>
        request<{ ok: boolean; new_etag: string; backup_path: string }>(
            '/config/save', { method: 'POST', body: JSON.stringify({ yaml, etag }) }
        ),
    versions: () => request<Array<{ filename: string; timestamp: number; user: string; path: string }>>('/config/versions'),
    revert: (version_path: string) =>
        request<{ ok: boolean; new_etag: string }>('/config/revert', { method: 'POST', body: JSON.stringify({ version_path }) }),
};

// =================== Run ===================
export const run = {
    status: () => request<{ running: boolean; pid?: number; mode?: string; uptime_sec?: number }>('/run/status'),
    precheck: () => request<{ checks: Array<{ name: string; status: string; detail: string }> }>('/run/precheck'),
    start: (mode: string) => request<{ ok: boolean; pid: number }>('/run/start', { method: 'POST', body: JSON.stringify({ mode }) }),
    stop: (force = false) => request<{ ok: boolean; signal: string }>('/run/stop', { method: 'POST', body: JSON.stringify({ force }) }),
};

// =================== DB ===================
export const db = {
    counts: () => request<Record<string, number>>('/db/counts'),
};

// =================== Qdrant ===================
export const qdrant = {
    stats: () => request<{ vectors_count: number; segments_count: number; status: string; stale: boolean }>('/qdrant/stats'),
    snapshot: () => request<Record<string, unknown>>('/qdrant/snapshot', { method: 'POST' }),
};

// =================== Metrics ===================
export const metrics = {
    system: () => request<{ cpu_pct: number; ram_pct: number; ram_used_mb: number; disk_free_gb: number; gpu?: { util_pct: number; vram_used_mb: number; vram_total_mb: number; temp_c: number } }>('/metrics/system'),
    projection: () => request<{ mean_per_day: number; lower95: number; upper95: number; rate_per_hr: number; window_sec: number; samples: number }>('/metrics/projection'),
    history: (range: string) => request<{ timestamps: number[]; cpu: number[]; ram: number[]; gpu_util: number[]; throughput: number[] }>(`/metrics/history?range=${range}`),
    coverage: () => request<{ keywords: string[]; years: number[]; matrix: number[][]; updated_at: string }>('/metrics/coverage'),
};

// =================== DLQ ===================
export const dlq = {
    list: (status = 'pending') => request<Array<{ id: number; paper_id: string; stage: string; error: string; retry_count: number; created_at: string; status: string }>>(`/dlq?status=${status}`),
    retry: (id: number) => request<{ ok: boolean }>(`/dlq/${id}/retry`, { method: 'POST' }),
    skip: (id: number) => request<{ ok: boolean }>(`/dlq/${id}/skip`, { method: 'POST' }),
};

// =================== Audit ===================
export const audit = {
    list: (params?: { user?: string; action?: string; page?: number }) => {
        const qs = new URLSearchParams();
        if (params?.user) qs.set('user', params.user);
        if (params?.action) qs.set('action', params.action);
        if (params?.page) qs.set('page', String(params.page));
        return request<{ items: Array<{ timestamp: string; user_id: string; action: string; detail: Record<string, unknown> }>; total: number }>(`/audit?${qs}`);
    },
};

// =================== Coverage Drilldown ===================
export const coverage = {
    drilldown: (keyword: string, year: number) =>
        request<{ keyword: string; year: number; papers_count: number; embedded_count: number; sources: Record<string, number>; gap_pct: number }>(
            `/db/coverage/drilldown?keyword=${encodeURIComponent(keyword)}&year=${year}`
        ),
};

// =================== User Documents ===================
export interface DocumentInfo {
    document_id: string;
    filename: string;
    title: string;
    status: 'pending' | 'processing' | 'ready' | 'failed';
    file_size: number;
    upload_date: string;
    error_message?: string;
}

export interface DocumentListResponse {
    documents: DocumentInfo[];
    total: number;
    counts: { total: number; pending: number; processing: number; ready: number; failed: number };
}

export const documents = {
    list: () => request<DocumentListResponse>('/documents'),

    upload: async (file: File): Promise<{ document_id: string; filename: string; status: string; message: string }> => {
        const formData = new FormData();
        formData.append('file', file);

        const headers: Record<string, string> = {};
        if (accessToken) {
            headers['Authorization'] = `Bearer ${accessToken}`;
        }

        const res = await fetch(`${API_BASE}/documents/upload`, {
            method: 'POST',
            headers,
            body: formData,
        });

        if (!res.ok) {
            const body = await res.text();
            throw new ApiError(res.status, body);
        }
        return res.json();
    },

    process: (documentId: string) =>
        request<{ document_id: string; status: string; message: string }>(
            `/documents/${documentId}/process`, { method: 'POST' }
        ),

    processAll: () =>
        request<{ queued_count: number; message: string }>(
            '/documents/process-all', { method: 'POST' }
        ),

    status: (documentId: string) =>
        request<{ document_id: string; title: string; status: string; internal_status: string }>(
            `/documents/${documentId}/status`
        ),

    delete: (documentId: string) =>
        request<{ deleted: boolean; message: string }>(
            `/documents/${documentId}`, { method: 'DELETE' }
        ),

    deleteBatch: (documentIds: string[]) =>
        request<{ deleted_count: number; failed: string[] }>(
            '/documents/batch', { method: 'DELETE', body: JSON.stringify(documentIds) }
        ),
};
