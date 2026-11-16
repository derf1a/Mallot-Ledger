/** 홈 — 최근 급여(실수령 · 공제)와 올해 연말정산 추정. 없으면 급여 화면으로 안내 */
import { Link } from 'react-router-dom'
import { salaryApi } from '../salary/api'
import { won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'

export default function SalaryCard() {
  const { data } = useLoad(() => salaryApi.view().catch(() => null), [])
  const last = data?.slips.filter((s) => s.kind === 'regular').at(-1) ?? data?.slips.at(-1)
  if (!data || !last) {
    return (
      <p className="muted small">
        급여명세서를 기록하면 실수령 · 4대보험 · 세금 흐름과 연말정산 추정을 볼 수 있어요. <Link to="/salary">급여 기록하기</Link>
      </p>
    )
  }
  const e = data.estimate
  return (
    <div className="home-salary">
      <strong className="num big">{won(last.net)}</strong>
      <span className="muted small">{last.pay_month} {last.kind_ko} 실수령 · 지급 {won(last.gross_pay)} · 공제 {won(last.deductions)}</span>
      {last.checks.some((c) => c.ok === false) && <span className="chip warn-chip small">검산이 안 맞는 공제가 있어요</span>}
      {e && <span className={`small ${e.refund >= 0 ? 'pos' : 'neg'}`}>{e.text}</span>}
    </div>
  )
}
