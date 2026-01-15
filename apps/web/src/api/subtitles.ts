export type ExportFormat = 'srt' | 'vtt' | 'ass' | 'json'
export type ContentMode = 'both' | 'primary_only' | 'secondary_only'
export type PrimaryPosition = 'top' | 'bottom'

export interface DownloadSubtitlesParams {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
}

export function getDownloadSubtitlesUrl(projectId: string, params: DownloadSubtitlesParams): string {
    const qs = new URLSearchParams({
        format: params.format,
        content: params.content,
        primary_position: params.primary_position,
    })
    return `/api/projects/${projectId}/subtitles/download?${qs.toString()}`
}

export interface SubtitleEditComputedEntry {
    segment_id: number
    start: number
    end: number
    secondary: string
    primary: string
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
    computed_entries: SubtitleEditComputedEntry[]
}

import { apiRequest } from './client'

export async function getSubtitleEditData(projectId: string): Promise<SubtitleEditDataResponse> {
    return apiRequest<SubtitleEditDataResponse>(`/projects/${projectId}/subtitles/edit-data`)
}
