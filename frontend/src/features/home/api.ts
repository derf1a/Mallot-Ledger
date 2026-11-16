/** 홈 API — 날마다 변동비·카테고리별 지난 기간·최근 기간 흐름 (백엔드 app/home) */
import { qs, request } from '../../shared/http'
import type { Period } from '../ledger/api'

/** 홈 그림용 추세 — 변동비는 요약과 같은 정의 */
export interface HomeDay {
  date: string
  /** 그날 변동비 (정산·환불은 뺌, 음수일 수 있음) */
  spent: number
  count: number
  top: { merchant: string; amount: number; icon: string }[]
}

export interface HomeCategoryDetail {
  count: number
  previous_spent: number
  merchants: { name: string; amount: number; count: number }[]
}

export interface HomeHistory extends Period {
  label: string
  variable: number
  income: number
  /** 정기지출에 연결된 거래 합계 (실제 나간 돈) */
  recurring: number
  current: boolean
}

export interface HomeTrend {
  period: Period
  today: string
  daily: HomeDay[]
  previous: Period & { daily: number[] }
  /** 카테고리 id (미분류는 'none') → 세부 */
  categories: Record<string, HomeCategoryDetail>
  history: HomeHistory[]
}

export const homeApi = {
  home: (on?: string) => request<HomeTrend>('GET', `/api/home${qs({ on })}`),
}
