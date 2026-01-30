import { useCallback, useEffect, useMemo, useState } from 'react'
import { createProject, deleteProject, listProjects } from '../api/projects'
import { useDocumentVisibility } from './useDocumentVisibility'
import { usePolling } from './usePolling'
import type { Project } from '../types/entities'
import type { CreateProjectRequest } from '../types/api'

export type SortOption = 'updated_desc' | 'updated_asc' | 'created_desc' | 'created_asc' | 'name_asc' | 'name_desc'

export const PROJECT_SORT_OPTIONS: { value: SortOption; label: string }[] = [
    { value: 'updated_desc', label: '最近更新' },
    { value: 'updated_asc', label: '最早更新' },
    { value: 'created_desc', label: '最近创建' },
    { value: 'created_asc', label: '最早创建' },
    { value: 'name_asc', label: '名称 A-Z' },
    { value: 'name_desc', label: '名称 Z-A' },
]

function toErrorMessage(err: unknown): string {
    if (err instanceof Error) return err.message
    return String(err)
}

function sortProjects(projects: Project[], sortBy: SortOption): Project[] {
    const sorted = [...projects]
    sorted.sort((a, b) => {
        switch (sortBy) {
            case 'updated_desc': {
                const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
                const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
                return bTime - aTime
            }
            case 'updated_asc': {
                const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
                const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
                return aTime - bTime
            }
            case 'created_desc': {
                const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
                const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
                return bTime - aTime
            }
            case 'created_asc': {
                const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
                const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
                return aTime - bTime
            }
            case 'name_asc':
                return (a.name || '').localeCompare(b.name || '')
            case 'name_desc':
                return (b.name || '').localeCompare(a.name || '')
            default:
                return 0
        }
    })
    return sorted
}

export function useProjects(options: { autoFetch?: boolean; pollIntervalMs?: number; initialSort?: SortOption } = {}) {
    const autoFetch = options.autoFetch ?? true
    const pollIntervalMs = options.pollIntervalMs ?? 15000

    const [projects, setProjects] = useState<Project[]>([])
    const [error, setError] = useState<string | null>(null)
    const [sortBy, setSortBy] = useState<SortOption>(options.initialSort ?? 'updated_desc')

    const [creating, setCreating] = useState(false)
    const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())

    const isVisible = useDocumentVisibility()
    const hasProcessing = projects.some((p) => p.status === 'processing')
    const shouldPoll = autoFetch && isVisible && hasProcessing

    const fetcher = useCallback((signal: AbortSignal) => listProjects({ signal }), [])

    const { loading: pollingLoading, refetch } = usePolling<Project[]>({
        fetcher,
        interval: pollIntervalMs,
        enabled: shouldPoll,
        onSuccess: (data) => {
            setProjects(data)
            setError(null)
        },
        onError: (err) => setError(err.message),
    })

    useEffect(() => {
        if (!autoFetch) return
        refetch()
    }, [autoFetch, refetch])

    const sortedProjects = useMemo(() => sortProjects(projects, sortBy), [projects, sortBy])

    const deleteProjectById = useCallback(async (projectId: string): Promise<boolean> => {
        setDeletingIds((prev) => new Set(prev).add(projectId))
        setError(null)
        try {
            await deleteProject(projectId)
            setProjects((prev) => prev.filter((p) => p.id !== projectId))
            return true
        } catch (err) {
            setError(toErrorMessage(err))
            return false
        } finally {
            setDeletingIds((prev) => {
                const next = new Set(prev)
                next.delete(projectId)
                return next
            })
        }
    }, [])

    const createProjectMutation = useCallback(async (data: CreateProjectRequest) => {
        setCreating(true)
        setError(null)
        try {
            const project = await createProject(data)
            setProjects((prev) => [project, ...prev])
            return project
        } catch (err) {
            setError(toErrorMessage(err))
            throw err
        } finally {
            setCreating(false)
        }
    }, [])

    return {
        data: sortedProjects,
        loading: pollingLoading || creating,
        error,
        clearError: () => setError(null),
        refetch,
        sortBy,
        setSortBy,
        sortOptions: PROJECT_SORT_OPTIONS,
        deleteProject: deleteProjectById,
        deletingIds,
        createProject: createProjectMutation,
        creating,
    }
}
