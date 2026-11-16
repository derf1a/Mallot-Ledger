/**
 * 변동비 예산 — 카테고리마다 한 줄(이름·남은 돈·막대). 막대의 세로 눈금은 '오늘까지 써도 되는 위치'(기간이 지난 비율).
 * 줄에 마우스를 올리면 예산 속도 대비·하루 쓸 수 있는 돈·지난 기간·많이 쓴 곳을 보여 주고, 누르면 가계부에서 그 카테고리를 연다.
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { HomeTrend } from './api'
import type { Summary } from '../ledger/api'
import Bar from '../../shared/ui/Bar'
import { useTip } from '../../shared/ui/useTip'
import { percent, won } from '../../shared/format'
import { changeText, progress } from './model'

interface Row {
  key: string
  icon: string
  name: string
  budget: number
  spent: number
}

export default function BudgetList({ s, trend }: { s: Summary; trend: HomeTrend | null }) {
  const { box, show, showAt, hide, node } = useTip()
  const today = trend?.today ?? s.period.start
  const pg = progress(s.period, today)
  const rows: Row[] = s.variable.categories
    .filter((c) => c.budget > 0 || c.spent !== 0)
    .map((c) => ({ key: String(c.id), icon: c.icon, name: c.name, budget: c.budget, spent: c.spent }))
  if (s.variable.uncategorized !== 0) rows.push({ key: 'none', icon: '❔', name: '미분류', budget: 0, spent: s.variable.uncategorized })
  const hidden = s.variable.categories.length - rows.filter((r) => r.key !== 'none').length

  const body = (r: Row): ReactNode => {
    const detail = trend?.categories[r.key]
    const remaining = r.budget - r.spent
    const expected = Math.round(r.budget * pg.ratio)
    const vsPrev = detail ? changeText(r.spent, detail.previous_spent) : null
    return (
      <>
        <b>{r.icon} {r.name}</b>
        <span className="viz-tip-row">
          <strong className="num">{won(r.spent)}</strong>
          <span className="muted">{r.budget > 0 ? `예산 ${won(r.budget)}의 ${percent(r.spent, r.budget)}%` : '예산 없음'}</span>
        </span>
        {r.budget > 0 && pg.current && (
          <span>
            오늘까지 예산 속도 {won(expected)}보다 <b>{won(Math.abs(r.spent - expected))} {r.spent > expected ? '더' : '덜'}</b> 썼어요
          </span>
        )}
        {r.budget > 0 && pg.current && remaining > 0 && pg.left > 0 && (
          <span className="muted">남은 {pg.left}일 동안 하루 {won(Math.floor(remaining / pg.left))}씩 쓸 수 있어요</span>
        )}
        {detail && (
          <span className="muted">
            지난 기간 {won(detail.previous_spent)}{vsPrev && ` · ${vsPrev}`}
          </span>
        )}
        {detail && detail.merchants.length > 0 && (
          <div className="home-tip-sub">
            <span>결제 {detail.count}건 · 많이 쓴 곳</span>
            {detail.merchants.map((m) => (
              <span key={m.name} className="home-tip-line">
                <span className="home-tip-name">{m.name || '(이름 없음)'}</span>
                <span className="num">{won(m.amount)}</span>
                <span className="muted home-tip-note">{m.count}회</span>
              </span>
            ))}
          </div>
        )}
        <span className="muted small">{r.key === 'none' ? '누르면 분류할 거래 보기' : '누르면 가계부에서 보기'}</span>
      </>
    )
  }

  return (
    <div className="home-budgets" ref={box} onMouseLeave={hide}>
      {rows.map((r) => (
        <Link key={r.key} className="budget-row home-budget" to={`/ledger?category=${r.key}&on=${s.period.start}`}
          onMouseMove={(e) => show(e, body(r))} onFocus={(e) => showAt(e.currentTarget, body(r))} onBlur={hide}>
          <div className="budget-head">
            <span>
              <span className="icon">{r.icon}</span> {r.name}
            </span>
            {r.budget > 0 ? (
              <span className={r.spent > r.budget ? 'neg' : 'amt-variable'}>
                {r.spent > r.budget ? `${won(r.spent - r.budget)} 초과` : `${won(r.budget - r.spent)} 남음`}
              </span>
            ) : (
              <span className="muted">{won(r.spent)} 사용 · 예산 없음</span>
            )}
          </div>
          {r.budget > 0 && <Bar value={r.spent} max={r.budget} tone="variable" pace={pg.current ? pg.ratio : undefined} />}
        </Link>
      ))}
      {hidden > 0 && <p className="muted small">예산·지출이 없는 카테고리 {hidden}개는 숨겼어요.</p>}
      {s.variable.refund_total > 0 && (
        <p className="muted small">↩️ 정산·환불로 {won(s.variable.refund_total)} 돌려받아 변동비에서 뺐어요</p>
      )}
      {s.variable.budget_total === 0 && (
        <p className="muted small">
          <Link to="/ledger/budget">변동비 관리</Link>에서 카테고리별 예산을 정할 수 있어요.
        </p>
      )}
      {node}
    </div>
  )
}
