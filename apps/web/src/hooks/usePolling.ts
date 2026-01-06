import { useEffect, useRef, useCallback, useState } from 'react'

interface UsePollingOptions<T> {
    fetcher: () => Promise<T>
    interval?: number
    enabled?: boolean
    onSuccess?: (data: T) => void
    onError?: (error: Error) => void
    shouldStop?: (data: T) => boolean
}

export function usePolling<T>({
    fetcher,
    interval = 2000,
    enabled = true,
    onSuccess,
    onError,
    shouldStop,
}: UsePollingOptions<T>) {
    const [data, setData] = useState<T | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<Error | null>(null)
    const timeoutRef = useRef<number | null>(null)
    const stoppedRef = useRef(false)

    const poll = useCallback(async () => {
        if (stoppedRef.current) return

        setLoading(true)
        try {
            const result = await fetcher()
            setData(result)
            setError(null)
            onSuccess?.(result)

            if (shouldStop?.(result)) {
                stoppedRef.current = true
                return
            }

            if (enabled && !stoppedRef.current) {
                timeoutRef.current = window.setTimeout(poll, interval)
            }
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err))
            setError(error)
            onError?.(error)

            // Continue polling on error
            if (enabled && !stoppedRef.current) {
                timeoutRef.current = window.setTimeout(poll, interval)
            }
        } finally {
            setLoading(false)
        }
    }, [fetcher, interval, enabled, onSuccess, onError, shouldStop])

    useEffect(() => {
        stoppedRef.current = false
        if (enabled) {
            poll()
        }
        return () => {
            stoppedRef.current = true
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [enabled, poll])

    const refetch = useCallback(() => {
        stoppedRef.current = false
        poll()
    }, [poll])

    return { data, loading, error, refetch }
}
