import { apiRequest } from './client'
import type { LLMHealthResponse } from '../types/api'

export async function getLLMHealth(): Promise<LLMHealthResponse> {
    return apiRequest<LLMHealthResponse>('/health/llm')
}

export async function checkLLMHealth(): Promise<LLMHealthResponse> {
    return apiRequest<LLMHealthResponse>('/health/llm', { method: 'POST' })
}
