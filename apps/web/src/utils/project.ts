import type { Project } from '../types/entities'

/**
 * Calculate progress percentage based on project status and current stage.
 */
export function getProgress(project: Project): number {
    if (project.status === 'completed') return 100
    if (project.status === 'failed') return (project.current_stage / 5) * 100
    return Math.min((project.current_stage / 5) * 100, 100)
}

