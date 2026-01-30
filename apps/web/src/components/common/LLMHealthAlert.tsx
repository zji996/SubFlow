import { useEffect, useState } from 'react'
import { getLLMHealth } from '../../api/health'
import type { LLMHealthResponse } from '../../types/api'

export function LLMHealthAlert() {
    const [status, setStatus] = useState<LLMHealthResponse | null>(null)

    useEffect(() => {
        getLLMHealth().then(setStatus).catch(() => { })
    }, [])

    if (!status || status.status === 'healthy' || status.status === 'unknown') return null

    const isUnhealthy = status.status === 'unhealthy'

    return (
        <div className={`mb-6 rounded-lg border p-4 transition-all duration-300 animate-in slide-in-from-top-2 ${isUnhealthy
                ? 'bg-rose-500/10 border-rose-500/20 text-rose-200'
                : 'bg-amber-500/10 border-amber-500/20 text-amber-200'
            }`}>
            <div className="flex items-start gap-3">
                <div className="shrink-0 mt-0.5">
                    {isUnhealthy ? (
                        <svg className="w-5 h-5 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    ) : (
                        <svg className="w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    )}
                </div>
                <div className="space-y-1">
                    <h3 className={`font-medium ${isUnhealthy ? 'text-rose-100' : 'text-amber-100'}`}>
                        {isUnhealthy ? 'LLM 服务不可用' : '部分 LLM 服务异常'}
                    </h3>
                    <div className="text-sm opacity-90">
                        {isUnhealthy ? (
                            <p>当前所有 LLM 服务均不可用，项目处理将无法进行。请检查服务配置。</p>
                        ) : (
                            <div className="space-y-1">
                                <p>部分 LLM 服务最近调用失败，可能影响翻译质量：</p>
                                <ul className="list-disc list-inside text-amber-200/80">
                                    {Object.values(status.providers)
                                        .filter(p => p.status === 'error')
                                        .map(p => (
                                            <li key={p.provider + p.model}>
                                                {p.provider} ({p.model})
                                            </li>
                                        ))
                                    }
                                </ul>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
