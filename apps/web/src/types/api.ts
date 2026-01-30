import type {
    ContentMode,
    ExportFormat,
    PrimaryPosition,
    PreviewSegment,
    PreviewStats,
    Project,
    SubtitleEditComputedEntry,
    SubtitleExport,
    VADRegionPreview,
} from './entities'

export interface CreateProjectRequest {
    name?: string
    media_url: string
    language?: string
    target_language: string
}

export interface DeleteProjectResponse {
    deleted: boolean
    project_id: string
}

export interface DownloadSubtitlesParams {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
}

export interface SubtitleEditDataResponse {
    asr_segments: Array<{
        id: number
        start: number
        end: number
        text: string
    }>
    asr_corrected_segments: Record<
        number,
        {
            id: number
            asr_segment_id: number
            text: string
        }
    >
    computed_entries: SubtitleEditComputedEntry[]
}

export interface CreateExportRequest {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
    edited_entries?: Array<{
        segment_id: number
        secondary?: string
        primary?: string
    }>
}

export interface ProjectPreviewResponse {
    project: {
        id: string
        name: string
        status: string
        current_stage: number
    }
    global_context: {
        topic?: string
        domain?: string
        style?: string
        glossary?: Record<string, string>
        translation_notes?: string[]
    }
    stats: PreviewStats
    vad_regions: VADRegionPreview[]
}

export interface PreviewSegmentsResponse {
    total: number
    segments: PreviewSegment[]
}

export interface UploadResponse {
    storage_key: string
    media_url: string
    size_bytes: number
    content_type: string
}

export interface UploadProgress {
    loaded: number
    total: number
    percent: number
}

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

export type ListProjectsResponse = Project[]
export type GetProjectResponse = Project
export type CreateProjectResponse = Project
export type ListExportsResponse = SubtitleExport[]
export type CreateExportResponse = SubtitleExport
