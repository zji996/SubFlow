export type ExportFormat = 'srt' | 'vtt' | 'ass' | 'json'
export type ContentMode = 'both' | 'primary_only' | 'secondary_only'
export type PrimaryPosition = 'top' | 'bottom'

export interface DownloadSubtitlesParams {
    format: ExportFormat
    content: ContentMode
    primary_position: PrimaryPosition
}

export function getDownloadSubtitlesUrl(projectId: string, params: DownloadSubtitlesParams): string {
    const qs = new URLSearchParams({
        format: params.format,
        content: params.content,
        primary_position: params.primary_position,
    })
    return `/projects/${projectId}/subtitles/download?${qs.toString()}`
}

