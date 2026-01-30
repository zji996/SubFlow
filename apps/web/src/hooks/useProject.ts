import { useCallback, useMemo, useState } from 'react'
import { deleteProject, getProject, retryStage, runAll, runStage } from '../api/projects'
import { STAGE_ORDER, getNextStageName } from '../constants/stages'
import type { Project, StageName, StageRun } from '../types/entities'
import { usePolling } from './usePolling'

function toErrorMessage(err: unknown): string {
    if (err instanceof Error) return err.message
    return String(err)
}

function getLatestStageRuns(project: Project | null): Map<StageName, StageRun> {
    const out = new Map<StageName, StageRun>()
    if (!project) return out
    for (const r of project.stage_runs || []) out.set(r.stage, r)
    return out
}

export function useProject(projectId?: string) {
    const [mutationLoading, setMutationLoading] = useState(false)
    const [mutationError, setMutationError] = useState<string | null>(null)

    const fetcher = useCallback(
        (signal: AbortSignal) => {
            if (!projectId) throw new Error('No project ID')
            return getProject(projectId, { signal })
        },
        [projectId],
    )

    const { data: project, loading: pollingLoading, error: pollingError, refetch } = usePolling<Project>({
        fetcher,
        interval: 5000,
        enabled: !!projectId,
        shouldStop: (data) => data.status === 'completed',
    })

    const latestStageRuns = useMemo(() => getLatestStageRuns(project), [project])

    const failedStage = useMemo(() => {
        return STAGE_ORDER.find((s) => latestStageRuns.get(s.name)?.status === 'failed') || null
    }, [latestStageRuns])

    const hasLLMCompleted = useMemo(() => {
        if (!project) return false
        return project.current_stage >= 5
    }, [project])

    const runNext = useCallback(async () => {
        if (!projectId || !project) return
        setMutationLoading(true)
        setMutationError(null)
        try {
            if (project.status === 'failed' && failedStage) {
                await retryStage(projectId, failedStage.name)
            } else {
                const next = getNextStageName(project.current_stage)
                if (!next) return
                await runStage(projectId, next)
            }
            refetch()
        } catch (err) {
            setMutationError(toErrorMessage(err))
        } finally {
            setMutationLoading(false)
        }
    }, [failedStage, project, projectId, refetch])

    const runAllStages = useCallback(async () => {
        if (!projectId) return
        setMutationLoading(true)
        setMutationError(null)
        try {
            await runAll(projectId)
            refetch()
        } catch (err) {
            setMutationError(toErrorMessage(err))
        } finally {
            setMutationLoading(false)
        }
    }, [projectId, refetch])

    const retry = useCallback(
        async (stage?: StageName) => {
            if (!projectId) return
            setMutationLoading(true)
            setMutationError(null)
            try {
                await retryStage(projectId, stage)
                refetch()
            } catch (err) {
                setMutationError(toErrorMessage(err))
            } finally {
                setMutationLoading(false)
            }
        },
        [projectId, refetch],
    )

    const remove = useCallback(async (): Promise<boolean> => {
        if (!projectId) return false
        setMutationLoading(true)
        setMutationError(null)
        try {
            await deleteProject(projectId)
            return true
        } catch (err) {
            setMutationError(toErrorMessage(err))
            return false
        } finally {
            setMutationLoading(false)
        }
    }, [projectId])

    return {
        data: project,
        loading: pollingLoading || mutationLoading,
        error: pollingError?.message ?? mutationError,
        refetch,
        runNext,
        runAll: runAllStages,
        retryStage: retry,
        deleteProject: remove,
        failedStage,
        hasLLMCompleted,
    }
}
