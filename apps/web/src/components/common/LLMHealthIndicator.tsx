import { useState, useRef, useEffect } from 'react'
import { getLLMHealth, checkLLMHealth } from '../../api/health'
import { LLMHealthPanel } from './LLMHealthPanel'
import type { LLMHealthResponse } from '../../types/api'

export function LLMHealthIndicator() {
    const [status, setStatus] = useState<LLMHealthResponse | null>(null)
    const [isOpen, setIsOpen] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)

    const fetchHealth = async () => {
        try {
            const data = await getLLMHealth()
            setStatus(data)
        } catch (e) {
            console.error('Failed to fetch LLM health', e)
        }
    }

    const refreshHealth = async () => {
        try {
            const data = await checkLLMHealth()
            setStatus(data)
        } catch (e) {
            console.error('Failed to refresh LLM health', e)
        }
    }

    useEffect(() => {
        fetchHealth()
        // Close on click outside
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const getStatusColor = () => {
        if (!status) return 'bg-gray-400'
        switch (status.status) {
            case 'healthy': return 'bg-gradient-to-br from-emerald-500 to-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.5)]'
            case 'degraded': return 'bg-gradient-to-br from-amber-500 to-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.5)]'
            case 'unhealthy': return 'bg-gradient-to-br from-rose-500 to-rose-400 shadow-[0_0_8px_rgba(239,68,68,0.5)] animate-pulse'
            default: return 'bg-gradient-to-br from-gray-500 to-gray-400'
        }
    }

    const getTooltip = () => {
        if (!status) return '检查 LLM 服务状态'
        switch (status.status) {
            case 'healthy': return 'LLM 服务正常'
            case 'degraded': return '部分 LLM 服务异常'
            case 'unhealthy': return 'LLM 服务不可用'
            default: return '未知状态'
        }
    }

    return (
        <div className="relative" ref={containerRef}>
            <button
                className={`w-3 h-3 rounded-full transition-all duration-300 cursor-pointer hover:scale-125 hover:brightness-110 ${getStatusColor()}`}
                onClick={() => setIsOpen(!isOpen)}
                title={getTooltip()}
            />

            {isOpen && (
                <div className="absolute right-0 top-full mt-4 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                    <LLMHealthPanel status={status} onRefresh={refreshHealth} />
                </div>
            )}
        </div>
    )
}
