import type { StageName } from '../types/entities'

export const STAGE_ORDER: { index: number; name: StageName; label: string }[] = [
    { index: 1, name: 'audio_preprocess', label: '音频处理' },
    { index: 2, name: 'vad', label: 'VAD 切分' },
    { index: 3, name: 'asr', label: 'ASR 识别' },
    { index: 4, name: 'llm_asr_correction', label: 'LLM ASR 纠错' },
    { index: 5, name: 'llm', label: 'LLM 翻译' },
]

export function getNextStageName(currentStage: number): StageName | null {
    const next = STAGE_ORDER.find((s) => s.index === currentStage + 1)
    return next ? next.name : null
}

