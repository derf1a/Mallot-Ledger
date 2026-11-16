/** 급여 관리 API — 급여명세서 기록 · 분석 · 명세서 이미지 판독 (백엔드 app/salary) */
import { qs, request } from '../../shared/http'
import type { SalaryParts, SalaryResult } from '../insights/api'

export type SlipKind = 'regular' | 'bonus' | 'retro' | 'other'
export type ItemKind = 'pay_taxable' | 'pay_nontaxable' | 'deduction'

export interface SlipItem { label: string; amount: number; kind: ItemKind }

export interface SlipInput {
  pay_month: string
  paid_on: string | null
  kind: SlipKind
  employer: string
  taxable_pay: number
  nontaxable_pay: number
  national_pension: number
  health_insurance: number
  long_term_care: number
  employment_insurance: number
  income_tax: number
  local_income_tax: number
  other_deductions: number
  net_pay: number | null
  items: SlipItem[]
  memo: string
  source: 'manual' | 'image' | 'estimate'
}

export interface SlipCheck { key: string; ok: boolean | null; text: string; expected?: number; actual?: number }

export interface Slip extends SlipInput {
  id: number
  created_at: string
  kind_ko: string
  gross_pay: number
  social: number
  taxes: number
  deductions: number
  net: number
  computed_net: number
  take_home_rate: number | null
  checks: SlipCheck[]
  deposit: { id: number; occurred_on: string; merchant: string } | null
  deposit_note: string | null
}

export interface SalaryMonth { month: string; gross: number; taxable: number; net: number; social: number; taxes: number }

export interface SalaryView {
  year: number
  years: number[]
  rules_year: number
  slips: Slip[]
  notes: string[]
  months: SalaryMonth[]
  totals: Record<string, number> | null
  rates: { tax: number | null; social: number | null; take_home: number | null } | null
  change: { from: string; to: string; diff: number; rate: number | null } | null
  projection: { through: string; rest_months: number; filled_before: number; filled_months: number; covered_months: number;
    months_in_year: number; avg_regular_taxable: number; gross_salary: number; withheld: number; social: number; note: string | null } | null
  estimate: { gross_salary: number; decided: number; withheld: number; refund: number; basis: 'ledger' | 'basic'; basis_ko: string;
    text: string } | null
}

export interface SlipDraft extends Omit<SlipInput, 'memo' | 'source'> {
  via: 'ocr' | 'vision'
  ocr_text: string | null
  note: string | null
}

/** 연봉 기준 — 연봉 구성(소비 분석 > 절세의 총급여 계산기와 같은 값)과 한 달 정기 급여 추정 */
export interface Contract {
  parts: SalaryParts | null
  gross_salary: number
  monthly: { taxable: number; nontaxable: number; social: number; income_tax: number; local_income_tax: number; net: number } | null
  lines: SalaryResult | null
}

export interface PlanDraft extends Omit<SlipInput, 'memo'> {
  memo: string
  basis: string
  deposit: number | null
  net: number
}

export interface Plan {
  year: number
  parts: SalaryParts | null
  regular_name: string | null
  calibrated_by: string | null
  drafts: PlanDraft[]
  others: { id: number; occurred_on: string; merchant: string; amount: number; kind: SlipKind }[]
  skipped: string[]
  note: string | null
}

export const salaryApi = {
  contract: () => request<Contract>('GET', '/api/salary/contract'),
  saveContract: (parts: SalaryParts) => request<Contract>('PUT', '/api/salary/contract', parts),
  plan: (year: number) => request<Plan>('GET', `/api/salary/plan?year=${year}`),
  applyPlan: (year: number, months: string[]) => request<{ created: number }>('POST', '/api/salary/plan', { year, months }),
  view: (year?: number) => request<SalaryView>('GET', `/api/salary${qs({ year })}`),
  create: (body: SlipInput) => request<Slip>('POST', '/api/salary', body),
  update: (id: number, body: SlipInput) => request<Slip>('PUT', `/api/salary/${id}`, body),
  remove: (id: number) => request<void>('DELETE', `/api/salary/${id}`),
  extract: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<SlipDraft>('POST', '/api/salary/extract', form)
  },
}

export const DEDUCTION_FIELDS = [
  ['national_pension', '국민연금'],
  ['health_insurance', '건강보험'],
  ['long_term_care', '장기요양'],
  ['employment_insurance', '고용보험'],
  ['income_tax', '소득세'],
  ['local_income_tax', '지방소득세'],
  ['other_deductions', '기타 공제'],
] as const
