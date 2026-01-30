import { apiRequest } from './client'
import type { PreviewSegmentsResponse, ProjectPreviewResponse } from '../types/api'

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
