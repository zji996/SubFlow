// API Types
export interface Job {
    id: string
    status: 'pending' | 'processing' | 'completed' | 'failed'
    result_url?: string | null
    error?: string | null
}

export interface CreateJobRequest {
    video_url: string
    target_language: string
}

// Base API client
const API_BASE = ''

async function request<T>(url: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${url}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options?.headers,
        },
    })

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(error.detail || `HTTP ${response.status}`)
    }

    return response.json()
}

// Job API functions
export async function createJob(data: CreateJobRequest): Promise<Job> {
    return request<Job>('/jobs', {
        method: 'POST',
        body: JSON.stringify(data),
    })
}

export async function getJob(jobId: string): Promise<Job> {
    return request<Job>(`/jobs/${jobId}`)
}

export async function getJobResult(jobId: string): Promise<string> {
    const response = await fetch(`/jobs/${jobId}/result`, {
        redirect: 'follow',
    })
    if (!response.ok) {
        throw new Error(`Failed to get result: ${response.status}`)
    }
    return response.text()
}
