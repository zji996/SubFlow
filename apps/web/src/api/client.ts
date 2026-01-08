export class ApiError extends Error {
    readonly status: number
    readonly detail: unknown

    constructor(message: string, status: number, detail: unknown) {
        super(message)
        this.name = 'ApiError'
        this.status = status
        this.detail = detail
    }
}

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

function formatFastApiDetail(detail: unknown): string | null {
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('; ')
    if (detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') {
        return (detail as { message: string }).message
    }
    return null
}

async function readErrorBody(response: Response): Promise<unknown> {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
        return (await response.json()) as JsonValue
    }
    return await response.text()
}

function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
    if (ms <= 0) return Promise.resolve()
    return new Promise((resolve, reject) => {
        const id = window.setTimeout(resolve, ms)
        if (!signal) return
        const onAbort = () => {
            clearTimeout(id)
            reject(new DOMException('Aborted', 'AbortError'))
        }
        if (signal.aborted) return onAbort()
        signal.addEventListener('abort', onAbort, { once: true })
    })
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
    json?: unknown
    retry?: number
    retryDelayMs?: number
}

const API_BASE = '/api'
const RETRYABLE_STATUS = new Set([408, 429, 502, 503, 504])

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const method = (options.method || 'GET').toUpperCase()
    const retries = options.retry ?? (method === 'GET' ? 1 : 0)
    const retryDelayMs = options.retryDelayMs ?? 300

    const headers = new Headers(options.headers)
    let body: BodyInit | undefined
    if (options.json !== undefined) {
        headers.set('Content-Type', 'application/json')
        body = JSON.stringify(options.json)
    }

    let attempt = 0
    // eslint-disable-next-line no-constant-condition
    while (true) {
        attempt += 1
        try {
            const response = await fetch(`${API_BASE}${path}`, {
                ...options,
                headers,
                body,
            })

            if (!response.ok) {
                const detail = await readErrorBody(response).catch(() => null)
                const message =
                    (detail && typeof detail === 'object' && 'detail' in detail
                        ? formatFastApiDetail((detail as { detail: unknown }).detail)
                        : null) || `HTTP ${response.status}`

                if (attempt <= retries + 1 && RETRYABLE_STATUS.has(response.status)) {
                    await sleep(retryDelayMs * attempt, options.signal)
                    continue
                }

                throw new ApiError(message, response.status, detail)
            }

            return (await response.json()) as T
        } catch (err) {
            if (err instanceof DOMException && err.name === 'AbortError') throw err
            if (attempt <= retries + 1) {
                await sleep(retryDelayMs * attempt, options.signal)
                continue
            }
            throw err
        }
    }
}
