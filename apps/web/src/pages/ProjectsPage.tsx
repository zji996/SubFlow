import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listProjects, type Project } from '../api/projects'
import { ProjectCard } from '../components/ProjectCard'
import { Spinner } from '../components/Spinner'

export default function ProjectsPage() {
    const [projects, setProjects] = useState<Project[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false

        async function fetchProjects() {
            try {
                const data = await listProjects()
                if (!cancelled) setProjects(data)
            } catch (err) {
                if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load projects')
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        fetchProjects()
        const interval = setInterval(fetchProjects, 5000)
        return () => {
            cancelled = true
            clearInterval(interval)
        }
    }, [])

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner size="lg" />
            </div>
        )
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-2xl font-bold">Projects</h1>
                    <p className="text-[--color-text-muted] mt-1">创建并管理翻译项目</p>
                </div>
                <Link to="/projects/new" className="btn-primary">
                    <span>➕</span> 新建项目
                </Link>
            </div>

            {error && (
                <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 mb-6">
                    {error}
                </div>
            )}

            {projects.length === 0 ? (
                <div className="glass-card p-12 text-center">
                    <div className="text-6xl mb-4">📭</div>
                    <h3 className="text-xl font-semibold mb-2">暂无项目</h3>
                    <p className="text-[--color-text-muted] mb-6">先创建一个项目开始使用</p>
                    <Link to="/projects/new" className="btn-primary inline-block">
                        创建项目
                    </Link>
                </div>
            ) : (
                <div className="grid gap-4 md:grid-cols-2">
                    {projects.map((p) => (
                        <ProjectCard key={p.id} project={p} />
                    ))}
                </div>
            )}
        </div>
    )
}

