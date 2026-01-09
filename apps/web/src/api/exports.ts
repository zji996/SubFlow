import { apiRequest, type ApiRequestOptions } from './client'

import type { ContentMode, ExportFormat, PrimaryPosition } from './subtitles'

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

export interface CreateExportRequest {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
    translation_style?: 'per_chunk' | 'full' | 'per_segment'
}

export async function listExports(projectId: string, options?: ApiRequestOptions): Promise<SubtitleExport[]> {
    return apiRequest<SubtitleExport[]>(`/projects/${projectId}/exports`, options)
}

export async function createExport(
    projectId: string,
    data: CreateExportRequest,
    options?: ApiRequestOptions,
): Promise<SubtitleExport> {
    return apiRequest<SubtitleExport>(`/projects/${projectId}/exports`, { ...options, method: 'POST', json: data })
}

