import type { DownloadSubtitlesParams, SubtitleEditDataResponse } from '../types/api'
import { apiRequest } from './client'

export function getDownloadSubtitlesUrl(projectId: string, params: DownloadSubtitlesParams): string {
    const qs = new URLSearchParams({
        format: params.format,
        content: params.content,
        primary_position: params.primary_position,
    })
    return `/api/projects/${projectId}/subtitles/download?${qs.toString()}`
}

export async function getSubtitleEditData(projectId: string): Promise<SubtitleEditDataResponse> {
    return apiRequest<SubtitleEditDataResponse>(`/projects/${projectId}/subtitles/edit-data`)
}
