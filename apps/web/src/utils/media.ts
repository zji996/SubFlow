/**
 * Get a human-friendly media name from a path/URL.
 */
export function getMediaName(url: string): string {
    if (!url) return '未知文件'
    const parts = url.split('/').pop() || url
    const decoded = decodeURIComponent(parts.split('?')[0])
    return decoded.length > 40 ? `${decoded.slice(0, 37)}...` : decoded
}

