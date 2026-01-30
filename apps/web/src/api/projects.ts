import { apiRequest, type ApiRequestOptions } from './client'
import type { Project, StageName } from '../types/entities'
import type { CreateProjectRequest, DeleteProjectResponse } from '../types/api'

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

export async function retryStage(id: string, stage?: StageName, options?: ApiRequestOptions): Promise<Project> {
    return apiRequest<Project>(`/projects/${id}/retry`, { ...options, method: 'POST', json: stage ? { stage } : {} })
}

export async function deleteProject(
    id: string,
    options?: ApiRequestOptions,
): Promise<DeleteProjectResponse> {
    return apiRequest<DeleteProjectResponse>(`/projects/${id}`, { ...options, method: 'DELETE' })
}
