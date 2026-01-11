export type ExportFormat = 'srt' | 'vtt' | 'ass' | 'json'
export type ContentMode = 'both' | 'primary_only' | 'secondary_only'
export type PrimaryPosition = 'top' | 'bottom'
export type TranslationStyle = 'per_chunk' | 'full' | 'per_segment'

export interface DownloadSubtitlesParams {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
    translation_style?: TranslationStyle
}

export function getDownloadSubtitlesUrl(projectId: string, params: DownloadSubtitlesParams): string {
    const qs = new URLSearchParams({
        format: params.format,
        content: params.content,
        primary_position: params.primary_position,
        translation_style: params.translation_style || 'per_chunk',
    })
    return `/api/projects/${projectId}/subtitles/download?${qs.toString()}`
}

export interface SubtitleEditComputedEntry {
    segment_id: number
    start: number
    end: number
    secondary: string
    primary_per_chunk: string
    primary_full: string
    primary_per_segment: string
    semantic_chunk_id: number | null
}

export interface SubtitleEditDataResponse {
    asr_segments: Array<{
        id: number
        start: number
        end: number
        text: string
    }>
    asr_corrected_segments: Record<number, {
        id: number
        asr_segment_id: number
        text: string
    }>
    semantic_chunks: Array<{
        id: number
        chunk_index: number
        text: string
        translation: string
        asr_segment_ids: number[]
        translation_chunks: Array<{
            text: string
            segment_ids: number[]
        }>
    }>
    computed_entries: SubtitleEditComputedEntry[]
}

import { apiRequest } from './client'

export async function getSubtitleEditData(projectId: string): Promise<SubtitleEditDataResponse> {
    return apiRequest<SubtitleEditDataResponse>(`/projects/${projectId}/subtitles/edit-data`)
}
