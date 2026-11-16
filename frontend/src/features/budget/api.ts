/** 변동비 관리 API — 할당 가능액·카테고리 예산·참고 사용액, 변동비 카테고리 (백엔드 app/budget) */
import { request } from '../../shared/http'
import type { Period } from '../ledger/api'

export interface Category {
  id: number
  name: string
  icon: string
  description: string
  budget: number
  sort_order: number
  is_system: number
}

/** 예산을 정할 때 참고할 사용액 (변동비 정의는 요약과 같음) */
export interface BudgetReference {
  /** 이번 기간 사용 */
  spent: number
  /** 이번 기간 거래 수 (정산·환불 포함) */
  count: number
  /** 지난 기간 사용 (그대로) */
  last: number
  /** 최근 끝난 기간 평균 — 100만 원 이상 한 건은 뺌. 데이터가 모자라면 null */
  average: number | null
  /** 평균에 쓴 기간별 사용 (오래된 순) */
  history: number[]
}

export interface BudgetCategory extends Omit<Category, 'is_system'>, BudgetReference {
  is_system: boolean
}

/** 변동비 관리 화면: 할당 가능액(주수입 − 정기지출)과 카테고리 예산·참고 사용액 */
export interface BudgetOverview {
  period: Period
  today: string
  income: number
  recurring_total: number
  pool: number
  categories: BudgetCategory[]
  uncategorized: BudgetReference
  reference: { last: string; periods: string[]; one_off: number }
}

export const budgetApi = {
  categories: () => request<Category[]>('GET', '/api/categories'),
  createCategory: (c: Partial<Category>) => request<Category>('POST', '/api/categories', c),
  updateCategory: (id: number, c: Partial<Category>) => request<Category>('PUT', `/api/categories/${id}`, c),
  deleteCategory: (id: number) => request<void>('DELETE', `/api/categories/${id}`),
  budget: () => request<BudgetOverview>('GET', '/api/budget'),
  saveBudgets: (budgets: { id: number; budget: number }[]) => request<BudgetOverview>('PUT', '/api/budget', { budgets }),
}
