import { apiRequest } from './client'

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

export interface PreviewSegmentsResponse {
    total: number
    segments: PreviewSegment[]
}

export async function getProjectPreview(projectId: string): Promise<ProjectPreviewResponse> {
    return apiRequest<ProjectPreviewResponse>(`/projects/${projectId}/preview`)
}

export async function getProjectPreviewSegments(
    projectId: string,
    options: { offset?: number; limit?: number; region_id?: number } = {}
): Promise<PreviewSegmentsResponse> {
    const params = new URLSearchParams()
    if (options.offset !== undefined) params.set('offset', String(options.offset))
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    if (options.region_id !== undefined) params.set('region_id', String(options.region_id))
    const qs = params.toString()
    return apiRequest<PreviewSegmentsResponse>(`/projects/${projectId}/preview/segments${qs ? `?${qs}` : ''}`)
}
