/**
 * File upload API
 */

import type { UploadProgress, UploadResponse } from '../types/api'

/**
 * Upload a file to the server with progress tracking
 */
export async function uploadFile(
    file: File,
    onProgress?: (progress: UploadProgress) => void,
    signal?: AbortSignal,
): Promise<UploadResponse> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable && onProgress) {
                onProgress({
                    loaded: e.loaded,
                    total: e.total,
                    percent: Math.round((e.loaded / e.total) * 100),
                })
            }
        })

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText) as UploadResponse
                    resolve(data)
                } catch {
                    reject(new Error('Invalid response format'))
                }
            } else {
                let message = `Upload failed: HTTP ${xhr.status}`
                try {
                    const err = JSON.parse(xhr.responseText)
                    if (err.detail) {
                        message = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail)
                    }
                } catch {
                    // ignore parse errors
                }
                reject(new Error(message))
            }
        })

        xhr.addEventListener('error', () => {
            reject(new Error('Network error during upload'))
        })

        xhr.addEventListener('abort', () => {
            reject(new DOMException('Upload aborted', 'AbortError'))
        })

        if (signal) {
            signal.addEventListener('abort', () => {
                xhr.abort()
            })
        }

        const formData = new FormData()
        formData.append('file', file)

        xhr.open('POST', '/api/upload')
        xhr.send(formData)
    })
}
