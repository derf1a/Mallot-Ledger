/** 정기지출 API — 정기지출 카테고리(칸)·항목·순서·이번 기간 상태·건너뛰기·반복 지출 제안 (백엔드 app/recurring) */
import { qs, request } from '../../shared/http'
import type { Period } from '../ledger/api'

export type RecurringKind = 'saving' | 'expense'

/** 정기지출 카테고리 (설정에서 관리) */
export interface RecurringGroup {
  id: number
  name: string
  kind: RecurringKind
  icon: string
  sort_order: number
  item_count?: number
}

export interface RecurringItemInput {
  name: string
  group_id: number
  icon: string
  amount: number
  /** null = 출금일 미정 (언제 나갈지 모르는 유동적인 지출) */
  day_of_month: number | null
  match_keyword: string
  memo: string
  active: boolean
  sort_order: number
}

export interface RecurringItem extends RecurringItemInput {
  id: number
  group_name: string
  group_kind: RecurringKind
  group_icon: string
  display_icon: string
}

export type RecurringStatus = 'paid' | 'upcoming' | 'missed' | 'unset' | 'floating' | 'skipped'

export interface RecurringStatusItem extends RecurringItem {
  /** 출금일 미정이면 null */
  due_date: string | null
  status: RecurringStatus
  transaction: { id: number; occurred_on: string; amount: number; merchant: string } | null
  /** 수입일 전(지난 기간 날짜)에 미리 나간 결제로 확인됨 — 은행 영업일·연휴로 출금일보다 앞서 나간 경우 */
  early: boolean
}

export type Cadence = 'monthly' | 'weekly'

/** 반복 지출 후보: 정기지출로 등록하지 않았는데 거래 이력에서 매월·매주 반복되는 지출 */
export interface RecurringCandidate {
  id: number
  merchant_key: string
  cadence: Cadence
  merchant: string
  /** 제안 금액 (최근 세 번 중 가장 흔한 금액) */
  amount: number
  keyword: string
  /** 매월 n일 / 요일 (0 = 월) */
  anchor: number
  occurrences: number
  first_on: string
  last_on: string
  next_on: string
  confidence: number
  status: 'pending' | 'accepted' | 'rejected'
  recurring_id: number | null
  tx_ids: number[]
  dates: string[]
  amount_min: number
  amount_max: number
  /** 첫 결제와 마지막 결제 사이에 빠진 주기 수 */
  missing: number
  warnings: string[]
  suggestion: RecurringItemInput
  /** 금액이 ±5% 안인 기존 정기지출 — 키워드가 비었거나 맞지 않아 연결되지 못한 같은 항목일 수 있다 */
  similar_item: (RecurringItemInput & { id: number }) | null
}

export const recurringApi = {
  recurringGroups: () => request<RecurringGroup[]>('GET', '/api/recurring-groups'),
  createRecurringGroup: (g: Omit<RecurringGroup, 'id'>) => request<RecurringGroup>('POST', '/api/recurring-groups', g),
  updateRecurringGroup: (id: number, g: Omit<RecurringGroup, 'id'>) =>
    request<RecurringGroup>('PUT', `/api/recurring-groups/${id}`, g),
  reorderRecurringGroups: (ids: number[]) => request<RecurringGroup[]>('PUT', '/api/recurring-groups/order', ids),
  deleteRecurringGroup: (id: number) => request<void>('DELETE', `/api/recurring-groups/${id}`),
  recurringItems: () => request<RecurringItem[]>('GET', '/api/recurring-items'),
  createRecurring: (r: RecurringItemInput) => request<RecurringItem>('POST', '/api/recurring-items', r),
  updateRecurring: (id: number, r: RecurringItemInput) => request<RecurringItem>('PUT', `/api/recurring-items/${id}`, r),
  reorderRecurring: (order: { group_id: number; item_ids: number[] }[]) =>
    request<RecurringItem[]>('PUT', '/api/recurring-items/order', order),
  skipRecurring: (id: number, on?: string) => request<{ skipped: boolean }>('POST', `/api/recurring-items/${id}/skip${qs({ on })}`),
  unskipRecurring: (id: number, on?: string) => request<{ skipped: boolean }>('DELETE', `/api/recurring-items/${id}/skip${qs({ on })}`),
  deleteRecurring: (id: number) => request<void>('DELETE', `/api/recurring-items/${id}`),
  recurringCandidates: () =>
    request<{ pending: RecurringCandidate[]; rejected: RecurringCandidate[] }>('GET', '/api/recurring-candidates'),
  acceptCandidate: (id: number, body: { item: RecurringItemInput; item_id?: number; link_past: boolean }) =>
    request<{ candidate: RecurringCandidate; item: RecurringItem; linked: number }>('POST', `/api/recurring-candidates/${id}/accept`, body),
  rejectCandidate: (id: number) => request<RecurringCandidate>('POST', `/api/recurring-candidates/${id}/reject`),
  restoreCandidate: (id: number) => request<RecurringCandidate>('POST', `/api/recurring-candidates/${id}/restore`),
  recurringStatus: (on?: string) =>
    request<{ period: Period; items: RecurringStatusItem[] }>('GET', `/api/recurring-status${qs({ on })}`),
}
