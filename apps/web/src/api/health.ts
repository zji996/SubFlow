import { apiRequest } from './client'

export interface LLMProviderHealth {
    status: 'ok' | 'error' | 'unknown'
    provider: string
    model: string
    last_success_at: string | null
    last_error_at: string | null
    last_error: string | null
    last_latency_ms: number | null
}

export interface LLMHealthResponse {
    status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
    providers: {
        [key: string]: LLMProviderHealth
    }
}

export async function getLLMHealth(): Promise<LLMHealthResponse> {
    return apiRequest<LLMHealthResponse>('/health/llm')
}

export async function checkLLMHealth(): Promise<LLMHealthResponse> {
    return apiRequest<LLMHealthResponse>('/health/llm', { method: 'POST' })
}
