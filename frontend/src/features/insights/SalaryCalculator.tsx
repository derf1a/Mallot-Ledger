/**
 * 총급여 계산기 — 받은 돈을 항목별로 넣으면 비과세를 뺀 총급여를 낸다. 계산은 서버(tax_rules.salary_lines) 한 곳에서만 해 세법 숫자가 화면과 갈라지지 않는다.
 * '이 금액으로 계산'을 누르면 절세 분석의 총급여로 저장하고, 입력값도 남겨 다시 열면 그대로 보인다.
 */
import { useEffect, useState } from 'react'
import { won } from '../../shared/format'
import { insightsApi, type SalaryParts, type SalaryResult } from './api'

const EMPTY: SalaryParts = {
  months: 12, base_monthly: 0, meal_monthly: 0, meal_provided: false, car_monthly: 0, childcare_monthly: 0, young_children: 0,
  bonus: 0, retro_pay: 0, settlement: 0, welfare_points: 0, welfare_public: false, other_taxable: 0, other_taxfree: 0,
}
type MoneyKey = 'base_monthly' | 'meal_monthly' | 'car_monthly' | 'childcare_monthly' | 'bonus' | 'retro_pay' | 'settlement' | 'welfare_points' | 'other_taxable' | 'other_taxfree'
const MONTHLY: { key: MoneyKey; label: string; hint: string }[] = [
  { key: 'base_monthly', label: '월정액 급여', hint: '기본급 + 고정수당 (세전)' },
  { key: 'meal_monthly', label: '식대', hint: '월 20만 원까지 비과세' },
  { key: 'car_monthly', label: '자가운전보조금', hint: '본인 차량 업무 사용 시 월 20만 원까지' },
  { key: 'childcare_monthly', label: '보육수당', hint: '6세 이하 자녀 1명당 월 20만 원까지' },
]
const YEARLY: { key: MoneyKey; label: string; hint: string }[] = [
  { key: 'bonus', label: '상여금', hint: '정기·성과 상여 합계' },
  { key: 'retro_pay', label: '임금협상 소급분', hint: '올해 일한 몫만' },
  { key: 'settlement', label: '임금협상 일시금', hint: '타결금·격려금' },
  { key: 'welfare_points', label: '복지포인트', hint: '민간 기업은 과세' },
  { key: 'other_taxable', label: '기타 과세 수당', hint: '연차수당·초과근무·명절 상여 등' },
  { key: 'other_taxfree', label: '기타 비과세', hint: '출산지원금 등 직접 확인한 것' },
]

function Money({ label, hint, value, onChange }: { label: string; hint: string; value: number; onChange: (v: number) => void }) {
  return (
    <label>
      {label}
      <input type="text" inputMode="numeric" value={value ? value.toLocaleString('ko-KR') : ''} placeholder="0"
        onChange={(e) => onChange(Number(e.target.value.replace(/\D/g, '')) || 0)} />
      <span className="muted small">{hint}</span>
    </label>
  )
}

export default function SalaryCalculator({ value, children_, busy, onUse }: {
  value: SalaryParts | null
  children_: number
  busy: boolean
  onUse: (parts: SalaryParts, gross: number) => void
}) {
  const [parts, setParts] = useState<SalaryParts>(() => ({ ...EMPTY, young_children: children_, ...value }))
  const [result, setResult] = useState<SalaryResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    const id = setTimeout(() => {
      insightsApi.salary(parts).then((r) => { if (live) { setResult(r); setError(null) } })
        .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    }, 200)
    return () => { live = false; clearTimeout(id) }
  }, [parts])
  const set = <K extends keyof SalaryParts>(key: K, v: SalaryParts[K]) => setParts((p) => ({ ...p, [key]: v }))
  return (
    <section className="salary-calc" aria-label="총급여 계산기">
      <h4>매달 받는 돈</h4>
      <div className="tax-profile-form">
        {MONTHLY.map((x) => <Money key={x.key} label={x.label} hint={x.hint} value={parts[x.key]} onChange={(v) => set(x.key, v)} />)}
        <label>
          올해 근무 개월 수
          <input type="number" inputMode="numeric" min={0} max={12} value={parts.months}
            onChange={(e) => set('months', Math.min(12, Math.max(0, Number(e.target.value) || 0)))} />
          <span className="muted small">중간에 입사·퇴사했으면 줄이세요</span>
        </label>
        <label>
          6세 이하 자녀 수
          <input type="number" inputMode="numeric" min={0} max={20} value={parts.young_children}
            onChange={(e) => set('young_children', Math.min(20, Math.max(0, Number(e.target.value) || 0)))} />
          <span className="muted small">보육수당 비과세에만 써요</span>
        </label>
      </div>
      <label className="salary-check">
        <input type="checkbox" checked={parts.meal_provided} onChange={(e) => set('meal_provided', e.target.checked)} />
        회사에서 식사를 제공받아요 (식대 비과세 없음)
      </label>
      <h4>한 해 합계로 받는 돈</h4>
      <div className="tax-profile-form">
        {YEARLY.map((x) => <Money key={x.key} label={x.label} hint={x.hint} value={parts[x.key]} onChange={(v) => set(x.key, v)} />)}
      </div>
      <label className="salary-check">
        <input type="checkbox" checked={parts.welfare_public} onChange={(e) => set('welfare_public', e.target.checked)} />
        공무원 복지점수예요 (비과세)
      </label>
      {error && <p className="alert warn small">{error}</p>}
      {result && result.lines.length > 0 && (
        <>
          <table className="tax-methods salary-lines">
            <thead><tr><th scope="col">항목</th><th scope="col">받은 돈</th><th scope="col">비과세</th><th scope="col">총급여에 포함</th></tr></thead>
            <tbody>
              {result.lines.map((x) => (
                <tr key={x.key}>
                  <th scope="row">{x.label}{x.note && <span className="muted small">{x.note}</span>}</th>
                  <td className="num" data-label="받은 돈">{won(x.income)}</td>
                  <td className="num" data-label="비과세">{x.taxfree ? won(x.taxfree) : '-'}</td>
                  <td className="num" data-label="총급여에 포함">{won(x.taxable)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="salary-total">
            <span className="muted small">받은 돈 {won(result.income)} − 비과세 {won(result.taxfree)}</span>
            <strong>총급여 {won(result.gross_salary)}</strong>
            <button type="button" className="primary" disabled={busy} onClick={() => onUse(parts, result.gross_salary)}>이 금액으로 계산</button>
          </div>
        </>
      )}
      <p className="muted small">비과세는 회사가 그 항목으로 지급할 때만 적용돼요. 원천징수영수증의 총급여가 있으면 그 값이 정확해요.</p>
    </section>
  )
}
