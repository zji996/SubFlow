import { apiRequest, type ApiRequestOptions } from './client'

export type ProjectStatus = 'pending' | 'processing' | 'paused' | 'completed' | 'failed'

export type StageName = 'audio_preprocess' | 'vad' | 'asr' | 'llm_asr_correction' | 'llm'

export type StageRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface StageRun {
    stage: StageName
    status: StageRunStatus
    started_at?: string | null
    completed_at?: string | null
    duration_ms?: number | null
    progress?: number | null
    progress_message?: string | null
    metrics?: {
        items_processed?: number
        items_total?: number
        items_per_second?: number
        llm_prompt_tokens?: number
        llm_completion_tokens?: number
        llm_tokens_per_second?: number
        llm_calls_count?: number
        active_tasks?: number
        max_concurrent?: number
        // 重试信息
        retry_count?: number
        retry_max?: number
        retry_reason?: string
        retry_status?: 'retrying' | 'recovered' | 'failed'
    } | null
    error_code?: string | null
    error_message?: string | null
    error?: string | null
    input_artifacts?: Record<string, string>
    output_artifacts?: Record<string, string>
}

export interface Project {
    id: string
    name: string
    media_url: string
    source_language?: string | null
    target_language: string
    status: ProjectStatus
    current_stage: number
    artifacts: Record<string, unknown>
    stage_runs: StageRun[]
    created_at?: string
    updated_at?: string
}

export interface CreateProjectRequest {
    name?: string
    media_url: string
    language?: string
    target_language: string
}

export async function createProject(data: CreateProjectRequest, options?: ApiRequestOptions): Promise<Project> {
    return apiRequest<Project>('/projects', { ...options, method: 'POST', json: data })
}

export async function listProjects(options?: ApiRequestOptions): Promise<Project[]> {
    return apiRequest<Project[]>('/projects', options)
}

export async function getProject(id: string, options?: ApiRequestOptions): Promise<Project> {
    return apiRequest<Project>(`/projects/${id}`, options)
}

export async function runStage(id: string, stage?: StageName, options?: ApiRequestOptions): Promise<Project> {
    return apiRequest<Project>(`/projects/${id}/run`, { ...options, method: 'POST', json: stage ? { stage } : {} })
}

export async function runAll(id: string, options?: ApiRequestOptions): Promise<Project> {
    return apiRequest<Project>(`/projects/${id}/run-all`, { ...options, method: 'POST', json: {} })
}

export async function deleteProject(
    id: string,
    options?: ApiRequestOptions,
): Promise<{ deleted: boolean; project_id: string }> {
    return apiRequest<{ deleted: boolean; project_id: string }>(`/projects/${id}`, { ...options, method: 'DELETE' })
}
