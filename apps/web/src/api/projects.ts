export type ProjectStatus = 'pending' | 'processing' | 'paused' | 'completed' | 'failed'

export type StageName = 'audio_preprocess' | 'vad' | 'asr' | 'llm_asr_correction' | 'llm' | 'export'

export interface Project {
    id: string
    name: string
    media_url: string
    source_language?: string | null
    target_language: string
    status: ProjectStatus
    current_stage: number
    artifacts: Record<string, any>
    stage_runs: Record<string, any>[]
}

export interface CreateProjectRequest {
    name?: string
    media_url: string
    language?: string
    target_language: string
}

export interface SubtitlePreview {
    format: 'srt'
    source: 'local' | 's3'
    content: string
}

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

export async function createProject(data: CreateProjectRequest): Promise<Project> {
    return request<Project>('/projects', {
        method: 'POST',
        body: JSON.stringify(data),
    })
}

export async function listProjects(): Promise<Project[]> {
    return request<Project[]>('/projects')
}

export async function getProject(id: string): Promise<Project> {
    return request<Project>(`/projects/${id}`)
}

export async function runStage(id: string, stage?: StageName): Promise<Project> {
    return request<Project>(`/projects/${id}/run`, {
        method: 'POST',
        body: JSON.stringify(stage ? { stage } : {}),
    })
}

export async function runAll(id: string): Promise<Project> {
    return request<Project>(`/projects/${id}/run-all`, {
        method: 'POST',
        body: JSON.stringify({}),
    })
}

export async function getSubtitles(id: string): Promise<SubtitlePreview> {
    return request<SubtitlePreview>(`/projects/${id}/subtitles`)
}
