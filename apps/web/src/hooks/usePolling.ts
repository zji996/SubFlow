import { useEffect, useRef, useCallback, useState } from 'react'

interface UsePollingOptions<T> {
    fetcher: (signal: AbortSignal) => Promise<T>
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
    const [loading, setLoading] = useState(true) // Start with loading=true for initial fetch
    const [error, setError] = useState<Error | null>(null)
    const timeoutRef = useRef<number | null>(null)
    const stoppedRef = useRef(false)
    const controllerRef = useRef<AbortController | null>(null)

    // Store callbacks in refs to avoid dependency changes causing re-polls
    const onSuccessRef = useRef(onSuccess)
    const onErrorRef = useRef(onError)
    const shouldStopRef = useRef(shouldStop)
    onSuccessRef.current = onSuccess
    onErrorRef.current = onError
    shouldStopRef.current = shouldStop

    const poll = useCallback(async () => {
        if (stoppedRef.current) return

        controllerRef.current?.abort()
        const controller = new AbortController()
        controllerRef.current = controller

        setLoading(true)
        try {
            const result = await fetcher(controller.signal)
            if (stoppedRef.current || controller.signal.aborted) return
            setData(result)
            setError(null)
            onSuccessRef.current?.(result)

            if (shouldStopRef.current?.(result)) {
                stoppedRef.current = true
                return
            }

            if (enabled && !stoppedRef.current) {
                timeoutRef.current = window.setTimeout(poll, interval)
            }
        } catch (err) {
            if (controller.signal.aborted) return
            const error = err instanceof Error ? err : new Error(String(err))
            setError(error)
            onErrorRef.current?.(error)

            // Continue polling on error
            if (enabled && !stoppedRef.current) {
                timeoutRef.current = window.setTimeout(poll, interval)
            }
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false)
            }
        }
    }, [fetcher, interval, enabled]) // Removed callback dependencies - using refs instead

    useEffect(() => {
        stoppedRef.current = false
        if (enabled) {
            poll()
        }
        return () => {
            stoppedRef.current = true
            controllerRef.current?.abort()
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [enabled, poll])

    const refetch = useCallback(() => {
        stoppedRef.current = false
        controllerRef.current?.abort()
        poll()
    }, [poll])

    return { data, loading, error, refetch }
}
