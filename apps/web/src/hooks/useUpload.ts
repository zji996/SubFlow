import { useCallback, useState } from 'react'
import { uploadFile } from '../api/uploads'
import type { UploadProgress, UploadResponse } from '../types/api'

function toErrorMessage(err: unknown): string {
    if (err instanceof Error) return err.message
    return String(err)
}

export function useUpload() {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [progress, setProgress] = useState<UploadProgress | null>(null)

    const upload = useCallback(async (file: File): Promise<UploadResponse> => {
        setLoading(true)
        setError(null)
        setProgress(null)
        try {
            return await uploadFile(file, (p) => setProgress(p))
        } catch (err) {
            setError(toErrorMessage(err))
            throw err
        } finally {
            setLoading(false)
        }
    }, [])

    const reset = useCallback(() => {
        setLoading(false)
        setError(null)
        setProgress(null)
    }, [])

    return { upload, loading, error, progress, reset }
}

