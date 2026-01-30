import { useState } from 'react'
import type { LLMHealthResponse } from '../../types/api'
import { Spinner } from './Spinner'

interface LLMHealthPanelProps {
    status: LLMHealthResponse | null
    onRefresh: () => Promise<void>
}

export function LLMHealthPanel({ status, onRefresh }: LLMHealthPanelProps) {
    const [isRefreshing, setIsRefreshing] = useState(false)

    const handleRefresh = async () => {
        setIsRefreshing(true)
        try {
            await onRefresh()
        } finally {
            setIsRefreshing(false)
        }
    }

    if (!status) return null

    return (
        <div className="glass-card p-4 min-w-[320px] max-w-[400px] space-y-4 text-sm text-gray-200 shadow-2xl backdrop-blur-xl border border-white/10 rounded-xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
                <h3 className="font-medium text-white flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-white/50"></span>
                    LLM 服务状态
                </h3>
                <button
                    onClick={handleRefresh}
                    disabled={isRefreshing}
                    className="p-1.5 hover:bg-white/10 rounded-lg transition-all duration-200 text-gray-400 hover:text-white disabled:opacity-50"
                    title="刷新状态"
                >
                    {isRefreshing ? <Spinner size="sm" /> : (
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.581m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    )}
                </button>
            </div>

            <div className="space-y-3">
                {Object.entries(status.providers).map(([key, provider]) => (
                    <div key={key} className="group bg-white/5 rounded-lg p-3 hover:bg-white/10 transition-colors border border-white/5">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">{key}</span>
                            <span className={`flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${provider.status === 'ok' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                                    provider.status === 'error' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                                        'bg-gray-500/10 text-gray-400 border border-gray-500/20'
                                }`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${provider.status === 'ok' ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]' :
                                        provider.status === 'error' ? 'bg-rose-400 shadow-[0_0_6px_rgba(251,113,133,0.5)]' : 'bg-gray-400'
                                    }`} />
                                {provider.status === 'ok' ? '正常' : provider.status === 'error' ? '异常' : '未知'}
                            </span>
                        </div>
                        <div className="flex justify-between items-center text-xs text-gray-400 mb-1">
                            <span className="font-mono text-white/70">{provider.provider} / {provider.model}</span>
                            {provider.last_latency_ms && (
                                <span className="flex items-center gap-1">
                                    <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                    {provider.last_latency_ms}ms
                                </span>
                            )}
                        </div>
                        {provider.last_error && (
                            <div className="mt-2 text-[10px] text-rose-300 break-words bg-rose-500/10 p-2 rounded border border-rose-500/20 font-mono">
                                {provider.last_error}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
