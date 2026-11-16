/** 가계부 API — 거래·기간 요약·개인설정·내 계좌·가맹점 분류 규칙·캡쳐 판독·뱅크샐러드 가져오기 (백엔드 app/ledger·capture·importer) */
import { qs, request } from '../../shared/http'
import type { RecurringKind, RecurringStatusItem } from '../recurring/api'

/** refund = 정산·환불 입금 (1/n 정산·부분 환불): 수입이 아니라 변동비에서 빠지는 돈 */
export type TxType = 'expense' | 'income' | 'transfer' | 'refund'

export type TransferKind = 'internal' | 'external'

export interface Period {
  start: string
  end: string
}

export interface Settings {
  owner_name: string
  monthly_income: number
  payday: number
  /** 빌린 돈을 받는 상대 (쉼표 구분) — 이 상대의 입금은 수입이 아니라 ±0 */
  loan_counterparties: string
  /** 가계부 검색 기본 범위 (최근 N개월, 0 = 전체) */
  search_months: number
}

export interface TxQuery {
  on?: string
  q?: string
  months?: number
  type?: TxType
  category_id?: string
  payment_method?: string
  needs_review?: boolean
  recurring?: 'linked' | 'unlinked'
  source?: 'manual' | 'image' | 'import'
  /** 변동비로 잡히는 거래만 (요약·변동비 관리의 사용액과 같은 정의) */
  variable?: boolean
  limit?: number
  offset?: number
}

export interface TransactionList {
  period: Period | null
  range: { start: string; end: string }
  total: number
  sums: { income: number; expense: number; transfer_out: number; refund: number }
  transactions: Transaction[]
}

export interface Account {
  id: number
  name: string
  keyword: string
}

export interface TransactionInput {
  occurred_on: string
  occurred_time?: string | null
  type: TxType
  transfer_kind: TransferKind | null
  amount: number
  merchant: string
  category_id: number | null
  recurring_id: number | null
  payment_method: string
  memo: string
  source: 'manual' | 'image' | 'import'
  /** 분류 출처: user(직접) / llm(AI 제안) / rule(가맹점 규칙) */
  category_source?: CategorySource | null
  reviewed?: boolean
}

export type CategorySource = 'user' | 'llm' | 'rule' | 'import'

export interface MerchantRule {
  id: number
  merchant_key: string
  category_id: number
  category_name: string
  category_icon: string
  source: 'user' | 'llm'
  hits: number
  updated_at: string
  tx_count: number
}

export interface Transaction extends TransactionInput {
  id: number
  merchant_key: string
  /** 수정 응답에만: 같은 가맹점인데 카테고리가 다른 다른 거래 수 */
  similar_count?: number
  needs_review: boolean
  category_name: string | null
  category_icon: string | null
  recurring_name: string | null
  recurring_kind: RecurringKind | null
  recurring_icon: string | null
  created_at: string
}

export interface Draft extends Omit<TransactionInput, 'recurring_id' | 'source'> {
  duplicate_of: number | null
  /** 저신뢰 경고 (미래 날짜, 큰 금액 등) */
  warnings: string[]
}

export interface ExtractionResult {
  extraction_id: number
  drafts: Draft[]
}

export interface ImportReport {
  rows: number
  period: { from: string; to: string } | null
  actions: Record<string, number>
  by_type: Record<string, number>
  mapping: { rule: string; count: number }[]
  dry_run: boolean
  batch_id?: number
  inserted?: number
  needs_review?: number
  recurring_matched?: number
  filled_by_rule?: number
}

export interface ImportBatch {
  id: number
  source: string
  file_name: string
  period_from: string | null
  period_to: string | null
  created_at: string
  tx_count: number
  stats: ImportReport
}

export interface FieldAccuracy {
  field: string
  label: string
  accuracy: number | null
}

export interface ExtractionStats {
  days: number
  logs: Record<'pending' | 'confirmed' | 'discarded' | 'failed', number>
  drafts: number
  included: number
  excluded: number
  duplicates_excluded: number
  false_positive_rate: number | null
  exact_match_rate: number | null
  fields: FieldAccuracy[]
  category_by_source: { source: string; accuracy: number | null; count: number }[]
  warning_precision: number | null
  latency_ms: { count: number; p50: number | null; p95: number | null }
  failure_rate: number | null
  daily: { day: string; exact_match_rate: number | null; count: number }[]
  prompt_version: string
}

export interface ExtractionLog {
  id: number
  created_at: string
  model: string
  prompt_version: string
  duration_ms: number | null
  status: 'pending' | 'confirmed' | 'discarded' | 'failed'
  error: string | null
  draft_count: number
  included_count: number
  image_path: string | null
}

export interface Summary {
  period: Period
  income: { planned: number; actual: number }
  recurring: {
    total: number
    saving_total: number
    expense_total: number
    groups: { group_id: number; group_name: string; kind: RecurringKind; icon: string; amount: number; paid: number }[]
    missed: number
    /** 이번 기간만 건너뛴 정기지출 합계 (정기지출 합계에서 빠짐) */
    skipped_total: number
    items: RecurringStatusItem[]
  }
  variable: {
    pool: number
    budget_total: number
    unallocated: number
    spent_total: number
    /** 정산·환불로 돌려받아 변동비에서 뺀 금액 */
    refund_total: number
    uncategorized: number
    categories: { id: number; name: string; icon: string; budget: number; spent: number; remaining: number }[]
  }
  needs_review: number
}

export const ledgerApi = {
  settings: () => request<Settings>('GET', '/api/settings'),
  saveSettings: (s: Partial<Settings>) => request<Settings>('PUT', '/api/settings', s),
  accounts: () => request<Account[]>('GET', '/api/accounts'),
  createAccount: (a: Omit<Account, 'id'>) => request<Account>('POST', '/api/accounts', a),
  updateAccount: (id: number, a: Omit<Account, 'id'>) => request<Account>('PUT', `/api/accounts/${id}`, a),
  deleteAccount: (id: number) => request<void>('DELETE', `/api/accounts/${id}`),
  transactions: (on?: string) => request<TransactionList>('GET', `/api/transactions${qs({ on })}`),
  searchTransactions: (query: TxQuery) => {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '' && v !== null) params.set(k, String(v))
    return request<TransactionList>('GET', `/api/transactions?${params.toString()}`)
  },
  paymentMethods: () => request<{ name: string; count: number }[]>('GET', '/api/transactions/payment-methods'),
  createTransaction: (t: TransactionInput) => request<Transaction>('POST', '/api/transactions', t),
  createTransactions: (t: TransactionInput[]) => request<Transaction[]>('POST', '/api/transactions/bulk', t),
  updateTransaction: (id: number, t: TransactionInput) => request<Transaction>('PUT', `/api/transactions/${id}`, t),
  deleteTransaction: (id: number) => request<void>('DELETE', `/api/transactions/${id}`),
  merchantRules: (q = '') => request<MerchantRule[]>('GET', `/api/merchant-rules?q=${encodeURIComponent(q)}`),
  suggestRule: (merchant: string) =>
    request<MerchantRule | null>('GET', `/api/merchant-rules/suggest?merchant=${encodeURIComponent(merchant)}`),
  updateRule: (id: number, category_id: number) => request<MerchantRule>('PUT', `/api/merchant-rules/${id}`, { category_id }),
  deleteRule: (id: number) => request<void>('DELETE', `/api/merchant-rules/${id}`),
  applyRulePast: (merchant: string, category_id: number) =>
    request<{ updated: number }>('POST', '/api/merchant-rules/apply-past', { merchant, category_id }),
  extract: (file: File) => {
    const form = new FormData()
    form.append('image', file)
    return request<ExtractionResult>('POST', '/api/transactions/extract', form)
  },
  confirmExtraction: (id: number, items: { draft_index: number; include: boolean; transaction?: TransactionInput }[]) =>
    request<Transaction[]>('POST', `/api/extractions/${id}/confirm`, { items }),
  discardExtraction: (id: number) => request<void>('POST', `/api/extractions/${id}/discard`),
  importBanksalad: (file: File, dryRun: boolean) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportReport>('POST', `/api/imports/banksalad?dry_run=${dryRun}`, form)
  },
  imports: () => request<ImportBatch[]>('GET', '/api/imports'),
  undoImport: (id: number) => request<{ deleted: number }>('DELETE', `/api/imports/${id}`),
  extractions: (limit = 50) => request<ExtractionLog[]>('GET', `/api/extractions?limit=${limit}`),
  extractionStats: (days = 90) => request<ExtractionStats>('GET', `/api/extractions/stats?days=${days}`),
  extractionStorage: () => request<{ images: number; bytes: number; logs: number }>('GET', '/api/extractions/storage'),
  deleteExtractionImages: () => request<{ removed: number }>('DELETE', '/api/extractions/images'),
  summary: (on?: string) => request<Summary>('GET', `/api/summary${qs({ on })}`),
}
