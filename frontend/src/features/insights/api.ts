/** 소비 습관 분석 API — 코드가 계산한 통계(/stats, LLM 없음: 고정 지출·저금·올해 절세 포함), LLM 보고서(실험실 spending_report 실행), 절세 내 정보 */
import type { Run } from '../runs/api'
import { request } from '../../shared/http'

export type Months = 1 | 3 | 6 | 12
export type HabitTone = 'good' | 'neutral' | 'watch'

export interface Span {
  start: string
  end: string
  periods: number
  label: string
}

export interface Fact {
  id: number
  group: string
  text: string
}

export interface PeriodStat {
  start: string
  end: string
  label: string
  in_window: boolean
  total: number
  one_off: number
  by_category: Record<string, number>
}

export interface FixedItem {
  id: number
  name: string
  group: string
  kind: 'saving' | 'expense'
  planned: number
  periods: number
  paid_periods: number
  window_avg: number
  paid_avg: number
  min: number
  max: number
  baseline_avg: number | null
}

export interface FixedStats {
  items: FixedItem[]
  groups: { name: string; kind: 'saving' | 'expense'; planned: number; window_avg: number; count: number }[]
  allocation: { income: number; saving: number; fixed: number; variable: number; left: number; saving_rate: number } | null
  planned: { saving: number; fixed: number }
  actual: { saving: number; fixed: number }
  periods: number
}

export type PaymentKind = 'credit' | 'debit' | 'none'
export type TaxItemKey = 'card' | 'pension' | 'housing_saving' | 'rent_loan' | 'insurance' | 'isa'
export type CardBucket = 'credit' | 'debit' | 'transit' | 'culture' | 'market' | 'none' | 'excluded'

/** 총급여 계산기 입력 — 월 금액은 세전, 나머지는 한 해 합계 */
export interface SalaryParts {
  months: number
  base_monthly: number
  meal_monthly: number
  meal_provided: boolean
  car_monthly: number
  childcare_monthly: number
  young_children: number
  bonus: number
  retro_pay: number
  settlement: number
  welfare_points: number
  welfare_public: boolean
  other_taxable: number
  other_taxfree: number
}

export interface SalaryResult {
  lines: { key: string; label: string; income: number; taxfree: number; taxable: number; note: string }[]
  income: number
  taxfree: number
  gross_salary: number
}

export interface TaxProfile {
  gross_salary: number
  salary_parts: SalaryParts | null
  homeless_head: boolean | null
  children: number
  payment_kinds: Record<string, PaymentKind>
}

export interface TaxItem {
  key: TaxItemKey
  title: string
  kind: 'income_deduction' | 'tax_credit' | 'info'
  status: 'ok' | 'check' | 'no' | 'none'
  paid: number
  total: number
  limit: number
  deduction: number
  effect: number
  room: number
  useful: number
  extra_saving: number
  requirement: string
  law: string
  sources: string[]
}

export interface TaxStats {
  year: number
  rules_year: number
  profile: TaxProfile
  gross: number
  gross_assumed: boolean
  available: boolean
  notes: string[]
  observed_from?: string
  items: TaxItem[]
  methods: { method: string; ytd: number; count: number; kind: PaymentKind; guessed: boolean }[]
  card: {
    ytd: Record<CardBucket, number>
    projected: Record<CardBucket, number>
    threshold: number
    total: number
    over: number
    deduction: number
    limit: number
    raw: number
  } | null
  summary: { tax_now: number; tax_without: number; saved: number; special: boolean; marginal: number; extra_total: number } | null
}

export interface Stats {
  periods: PeriodStat[]
  category_order: string[]
  categories: { name: string; avg: number; budget: number; baseline_avg: number | null; count: number }[]
  weekday: { day: string; avg: number; total: number; days: number }[]
  hours: { hour: number; amount: number; count: number }[] | null
  hour_coverage: number
  merchants: { name: string; count: number; sum: number; avg: number; category: string }[]
  kpis: {
    avg_total: number
    ledger_total: number
    one_off_total: number
    one_off_count: number
    baseline_avg: number | null
    budget_total: number
    pool: number | null
    small_count_share: number | null
    small_amount_share: number | null
    night_share: number | null
    payday_ratio: number | null
    spend_count: number
    saving_rate: number | null
    tax_extra: number | null
  }
  current: { start: string; end: string; elapsed: number; days: number; spent: number; pace: number } | null
  fixed: FixedStats
  tax: TaxStats
}

export interface SpendingFacts {
  months: Months
  window: Span
  baseline: Span | null
  current: { start: string; end: string }
  facts: Fact[]
  notes: string[]
  categories: { name: string; description: string; budget: number }[]
  stats: Stats
}

export interface Note {
  title: string
  tone: HabitTone
  detail: string
  fact_ids: number[]
}

export interface TaxTip {
  item: TaxItemKey | 'other'
  title: string
  action: string
  reason: string
  fact_ids: number[]
  extra_saving: number
  useful: number
  effect: number
}

export interface SpendingReport {
  title: string
  headline: string
  summary: string
  habits: Note[]
  /** 고정비·저금 — 예전 보고서에는 없다 */
  money_notes?: Note[]
  /** 절세 — 금액은 코드가 붙인 값 */
  tax_tips?: TaxTip[]
  category_notes: { category: string; note: string; fact_ids: number[] }[]
  suggestions: { action: string; reason: string; fact_ids: number[]; monthly_saving: number }[]
  questions: string[]
  months: Months
  window: Span
  baseline: Span | null
  citations_dropped: number
  ungrounded: number
  facts: Fact[]
  stats: Stats
}

export const insightsApi = {
  stats: (months: Months) => request<SpendingFacts>('GET', `/api/spending/stats?months=${months}`),
  reports: () => request<Run[]>('GET', '/api/spending/reports'),
  createReport: (body: { months: Months; model: string }) => request<Run>('POST', '/api/spending/reports', body),
  report: (id: number) => request<Run & { report: SpendingReport | null }>('GET', `/api/spending/reports/${id}`),
  saveTaxProfile: (body: TaxProfile) => request<TaxStats>('PUT', '/api/spending/tax-profile', body),
  salary: (body: SalaryParts) => request<SalaryResult>('POST', '/api/spending/salary', body),
}
