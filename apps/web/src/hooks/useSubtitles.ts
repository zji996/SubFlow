import { useCallback } from 'react'
import { getSubtitleEditData } from '../api/subtitles'
import type { SubtitleEditDataResponse } from '../types/api'
import { usePolling } from './usePolling'

export function useSubtitles(projectId?: string) {
    const fetcher = useCallback(
        (_signal: AbortSignal) => {
            if (!projectId) throw new Error('No project ID')
            return getSubtitleEditData(projectId)
        },
        [projectId],
    )

    const { data, loading, error, refetch } = usePolling<SubtitleEditDataResponse>({
        fetcher,
        enabled: !!projectId,
        shouldStop: () => true,
        pollOnError: false,
    })

    return {
        data,
        loading,
        error: error?.message ?? null,
        refetch,
    }
}

