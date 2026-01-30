import { apiRequest, type ApiRequestOptions } from './client'

import type { CreateExportRequest } from '../types/api'
import type { SubtitleExport } from '../types/entities'

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
