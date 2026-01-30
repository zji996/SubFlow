import { useCallback, useEffect, useMemo, useState } from 'react'
import { getProjectPreview, getProjectPreviewSegments } from '../api/preview'
import type { PreviewSegment } from '../types/entities'
import type { ProjectPreviewResponse } from '../types/api'
import { usePolling } from './usePolling'

function toErrorMessage(err: unknown): string {
    if (err instanceof Error) return err.message
    return String(err)
}

export function usePreview(projectId?: string) {
    const [segments, setSegments] = useState<PreviewSegment[]>([])
    const [segmentsTotal, setSegmentsTotal] = useState(0)
    const [segmentsLoading, setSegmentsLoading] = useState(false)
    const [segmentsError, setSegmentsError] = useState<string | null>(null)

    const [selectedRegion, setSelectedRegion] = useState<number | null>(null)
    const [offset, setOffset] = useState(0)
    const limit = 50

    const previewFetcher = useCallback(
        (_signal: AbortSignal) => {
            if (!projectId) throw new Error('No project ID')
            return getProjectPreview(projectId)
        },
        [projectId],
    )

    const { data: preview, loading: previewLoading, error: previewError, refetch } = usePolling<ProjectPreviewResponse>({
        fetcher: previewFetcher,
        enabled: !!projectId,
        shouldStop: () => true,
        pollOnError: false,
    })

    const loadSegments = useCallback(
        async (nextOffset: number) => {
            if (!projectId) return
            setSegmentsLoading(true)
            setSegmentsError(null)
            try {
                const data = await getProjectPreviewSegments(projectId, {
                    offset: nextOffset,
                    limit,
                    region_id: selectedRegion ?? undefined,
                })
                setSegments(data.segments)
                setSegmentsTotal(data.total)
                setOffset(nextOffset)
            } catch (err) {
                setSegmentsError(toErrorMessage(err))
            } finally {
                setSegmentsLoading(false)
            }
        },
        [projectId, selectedRegion],
    )

    useEffect(() => {
        if (!projectId) return
        refetch()
    }, [projectId, refetch])

    useEffect(() => {
        if (!preview) return
        void loadSegments(0)
    }, [preview, selectedRegion, loadSegments])

    const error = useMemo(() => previewError?.message ?? segmentsError, [previewError, segmentsError])
    const loading = previewLoading || segmentsLoading

    return {
        data: preview,
        loading,
        error,
        refetch,
        segments,
        segmentsTotal,
        segmentsLoading,
        segmentsError,
        selectedRegion,
        setSelectedRegion,
        offset,
        loadSegments,
        limit,
    }
}

