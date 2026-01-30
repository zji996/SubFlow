export type ProjectStatus = 'pending' | 'processing' | 'paused' | 'completed' | 'failed'

export type StageName = 'audio_preprocess' | 'vad' | 'asr' | 'llm_asr_correction' | 'llm'

export type StageRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface StageRunMetrics {
    items_processed?: number
    items_total?: number
    items_per_second?: number
    llm_prompt_tokens?: number
    llm_completion_tokens?: number
    llm_tokens_per_second?: number
    llm_calls_count?: number
    active_tasks?: number
    max_concurrent?: number
    retry_count?: number
    retry_max?: number
    retry_reason?: string
    retry_status?: 'retrying' | 'recovered' | 'failed'
}

export interface StageRun {
    stage: StageName
    status: StageRunStatus
    started_at?: string | null
    completed_at?: string | null
    duration_ms?: number | null
    progress?: number | null
    progress_message?: string | null
    metrics?: StageRunMetrics | null
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

export type ExportFormat = 'srt' | 'vtt' | 'ass' | 'json'
export type ContentMode = 'both' | 'primary_only' | 'secondary_only'
export type PrimaryPosition = 'top' | 'bottom'

export type ExportSource = 'auto' | 'edited'

export interface SubtitleExport {
    id: string
    created_at: string
    format: ExportFormat
    content_mode: ContentMode
    source: ExportSource
    download_url: string
    config_json?: string
    storage_key?: string
    entries_name?: string | null
}

export interface SubtitleEditComputedEntry {
    segment_id: number
    start: number
    end: number
    secondary: string
    primary: string
}

export interface VADRegionPreview {
    region_id: number
    start: number
    end: number
    segment_count: number
}

export interface PreviewStats {
    vad_region_count: number
    asr_segment_count: number
    corrected_count: number
    semantic_chunk_count: number
    total_duration_s: number
}

export interface SemanticChunkInfo {
    id: number
    text: string
    translation: string
    translation_chunk_text: string
}

export interface PreviewSegment {
    id: number
    start: number
    end: number
    text: string
    corrected_text: string | null
    semantic_chunk: SemanticChunkInfo | null
}

