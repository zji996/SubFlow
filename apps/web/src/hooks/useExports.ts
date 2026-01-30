import { useCallback, useEffect, useMemo, useState } from 'react'
import { createExport, listExports } from '../api/exports'
import { ApiError } from '../api/client'
import type { CreateExportRequest } from '../types/api'
import type { SubtitleExport } from '../types/entities'
import { usePolling } from './usePolling'

function toErrorMessage(err: unknown): string {
    if (err instanceof ApiError) {
        const detailText =
            err.detail == null
                ? null
                : typeof err.detail === 'string'
                    ? err.detail
                    : JSON.stringify(err.detail, null, 2)

        const base = `${err.message} (HTTP ${err.status})`
        if (!detailText || detailText === err.message) return base
        return `${base}\n${detailText}`
    }
    if (err instanceof Error) return err.message
    return String(err)
}

export function useExports(projectId?: string, options: { enabled?: boolean } = {}) {
    const enabled = options.enabled ?? true

    const [exports, setExports] = useState<SubtitleExport[]>([])
    const [error, setError] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)

    const fetcher = useCallback(
        (signal: AbortSignal) => {
            if (!projectId) throw new Error('No project ID')
            return listExports(projectId, { signal })
        },
        [projectId],
    )

    const { loading: pollingLoading, error: pollingError, refetch } = usePolling<SubtitleExport[]>({
        fetcher,
        enabled: enabled && !!projectId,
        shouldStop: () => true,
        pollOnError: false,
        onSuccess: (items) => {
            setExports(items)
            setError(null)
        },
        onError: (err) => setError(err.message),
    })

    useEffect(() => {
        if (!enabled || !projectId) return
        refetch()
    }, [enabled, projectId, refetch])

    const create = useCallback(
        async (data: CreateExportRequest) => {
            if (!projectId) throw new Error('No project ID')
            setSaving(true)
            setError(null)
            try {
                const exp = await createExport(projectId, data)
                setExports((prev) => [exp, ...prev.filter((x) => x.id !== exp.id)])
                return exp
            } catch (err) {
                setError(toErrorMessage(err))
                throw err
            } finally {
                setSaving(false)
            }
        },
        [projectId],
    )

    const mergedError = useMemo(() => pollingError?.message ?? error, [pollingError, error])

    return {
        data: exports,
        loading: pollingLoading,
        saving,
        error: mergedError,
        refetch,
        createExport: create,
    }
}
