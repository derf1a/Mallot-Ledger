/** 소비 습관 화면 도우미 (컴포넌트가 아닌 것 — Fast Refresh) */

/** 축 숫자: 12만 · 1.2억 */
export function compact(n: number): string {
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(1).replace(/\.0$/, '')}억`
  if (Math.abs(n) >= 1e4) return `${Math.round(n / 1e4).toLocaleString('ko-KR')}만`
  return n.toLocaleString('ko-KR')
}

export const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(digits)}%`)

export const change = (now: number, before: number | null) =>
  before ? `${now >= before ? '+' : ''}${(((now - before) / before) * 100).toFixed(0)}%` : null

const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)']
export const OTHER = 'var(--series-other)'

/** 카테고리 색 — 설정의 카테고리 순서로 고정(기간·필터가 바뀌어도 같은 색), 다섯 번째 뒤와 미분류는 회색 */
export function categoryColor(name: string, order: string[]): string {
  const i = order.indexOf(name)
  return i >= 0 && i < SERIES.length ? SERIES[i] : OTHER
}

/** 소비 습관 보고서에 쓸 모델 (빈 값 = 설정 > LLM 의 기본) */
export const MODELS = [
  { key: '', label: '기본 모델' },
  { key: 'claude-sonnet-5-5', label: 'Sonnet 5.5 (빠름)' },
  { key: 'claude-haiku-5-5', label: 'Haiku 5.5 (가벼움)' },
  { key: 'local', label: '로컬 LLM' },
]
