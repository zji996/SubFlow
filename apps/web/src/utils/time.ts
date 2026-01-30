/**
 * Format a time-like value.
 *
 * - When `value` is a number, treats it as seconds and formats as `mm:ss.mmm`.
 * - When `value` is a string, treats it as an ISO datetime and formats using `toLocaleString()`.
 */
export function formatTime(value?: number | string | null): string {
    if (value == null) return '-'
    if (typeof value === 'number') {
        const mins = Math.floor(value / 60)
        const secs = Math.floor(value % 60)
        const ms = Math.floor((value % 1) * 1000)
        return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
    }

    const dt = new Date(value)
    if (Number.isNaN(dt.getTime())) return value
    return dt.toLocaleString()
}

/**
 * Format a timestamp (seconds) as `HH:MM:SS,mmm`.
 * Commonly used by SRT.
 */
export function formatTimestamp(seconds: number): string {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}

export type DurationUnit = 's' | 'ms'
export type DurationStyle = 'clock' | 'human'

/**
 * Format a duration value.
 *
 * - `style="clock"`: `m:ss` (best for short durations)
 * - `style="human"`: `Xm Ys` or `Xs` (best for job-like durations)
 */
export function formatDuration(
    value: number,
    options: { unit?: DurationUnit; style?: DurationStyle } = {},
): string {
    const unit = options.unit ?? 's'
    const style = options.style ?? 'clock'

    const seconds = unit === 'ms' ? value / 1000 : value
    if (!Number.isFinite(seconds) || seconds < 0) return '-'

    if (style === 'human') {
        const ms = unit === 'ms' ? value : value * 1000
        if (ms >= 60000) {
            const mins = Math.floor(ms / 60000)
            const secs = Math.floor((ms % 60000) / 1000)
            return `${mins}m ${secs}s`
        }
        return `${(ms / 1000).toFixed(1)}s`
    }

    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${String(secs).padStart(2, '0')}`
}

/**
 * Format an ISO datetime relative to now in Chinese.
 */
export function formatRelativeTime(isoString?: string | null): string {
    if (!isoString) return ''
    const date = new Date(isoString)
    if (Number.isNaN(date.getTime())) return ''

    const now = Date.now()
    const diff = now - date.getTime()
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}天前`
    if (hours > 0) return `${hours}小时前`
    if (minutes > 0) return `${minutes}分钟前`
    return '刚刚'
}

