/**
 * 주수입 배분 — 정기·저금 / 정기·지출 그룹 / 변동비 예산 / 미배정을 한 줄 100% 막대로.
 * 칸에 마우스를 올리면(키보드 포커스도) 그 칸에 든 항목(정기지출 항목·카테고리 예산)을 금액과 함께 보여 준다.
 */
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Summary } from '../ledger/api'
import { useTip } from '../../shared/ui/useTip'
import { percent, shortDate, won } from '../../shared/format'
import { STATUS_LABEL } from './model'

const LIST_MAX = 8

interface Seg {
  key: string
  label: string
  amount: number
  color: string
  cls: string
  to?: string
  lines: { name: string; amount: number; note?: string }[]
  hint?: string
}

function segments(s: Summary): Seg[] {
  const groups = [...s.recurring.groups].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'saving' ? -1 : 1))
  return [
    ...groups.map((g) => ({
      key: `g${g.group_id}`,
      label: `${g.icon} ${g.group_name}`,
      amount: g.amount,
      color: g.kind === 'saving' ? 'var(--c-saving)' : 'var(--c-fixed)',
      cls: g.kind === 'saving' ? 'amt-saving' : 'amt-fixed',
      to: '/ledger/recurring',
      lines: s.recurring.items
        .filter((i) => i.group_id === g.group_id && i.status !== 'skipped' && i.amount > 0)
        .map((i) => ({
          name: `${i.display_icon} ${i.name}`,
          amount: i.amount,
          note: i.status === 'paid' && i.transaction ? `${shortDate(i.transaction.occurred_on)} ${i.early ? '미리 ' : ''}냄` : STATUS_LABEL[i.status],
        })),
    })),
    {
      key: 'variable',
      label: '변동비 예산',
      amount: s.variable.budget_total,
      color: 'var(--c-variable)',
      cls: 'amt-variable',
      to: '/ledger/budget',
      lines: s.variable.categories.filter((c) => c.budget > 0).map((c) => ({ name: `${c.icon} ${c.name}`, amount: c.budget })),
    },
    {
      key: 'free',
      label: '미배정',
      amount: Math.max(s.variable.unallocated, 0),
      color: 'var(--border)',
      cls: 'muted',
      to: '/ledger/budget',
      lines: [],
      hint: '주수입에서 정기지출과 변동비 예산을 빼고 남은 돈이에요. 변동비 관리(Budget)에서 카테고리 예산으로 배정할 수 있어요.',
    },
  ].filter((x) => x.amount > 0)
}

export default function Allocation({ s }: { s: Summary }) {
  const income = s.income.planned
  const navigate = useNavigate()
  const { box, show, showAt, hide, node } = useTip()
  const segs = segments(s)
  const whole = Math.max(income, s.recurring.total + s.variable.budget_total)

  const body = (g: Seg): ReactNode => (
    <>
      <span className="viz-tip-row">
        <i className="viz-tip-key" style={{ background: g.color }} />
        <strong className="num">{won(g.amount)}</strong>
        <span className="muted">{g.label} · 주수입의 {percent(g.amount, income)}%</span>
      </span>
      {g.lines.slice(0, LIST_MAX).map((l) => (
        <span key={l.name} className="home-tip-line">
          <span className="home-tip-name">{l.name}</span>
          <span className="num">{won(l.amount)}</span>
          {l.note && <span className="muted home-tip-note">{l.note}</span>}
        </span>
      ))}
      {g.lines.length > LIST_MAX && <span className="muted">그 밖에 {g.lines.length - LIST_MAX}개</span>}
      {g.hint && <span className="muted">{g.hint}</span>}
    </>
  )

  return (
    <>
      <div className="stat-row">
        <div title={s.income.actual ? `이번 기간 실제 입금 ${won(s.income.actual)}` : '이번 기간 아직 수입 입금이 없어요'}>
          <span className="muted">주수입</span>
          <strong className="pos">{won(income)}</strong>
        </div>
        <div>
          <span className="muted">정기 · 저금</span>
          <strong className="amt-saving">{won(s.recurring.saving_total)}</strong>
        </div>
        <div>
          <span className="muted">정기 · 지출</span>
          <strong className="amt-fixed">{won(s.recurring.expense_total)}</strong>
        </div>
        <div>
          <span className="muted">변동비 가능</span>
          <strong className={s.variable.pool < 0 ? 'neg' : 'amt-variable'}>{won(s.variable.pool)}</strong>
        </div>
      </div>
      <div className="home-alloc" ref={box} onMouseLeave={hide} role="group" aria-label="주수입 배분">
        <div className="stack-bar tall">
          {segs.map((g) => (
            <button key={g.key} type="button" className="stack-seg" aria-label={`${g.label} ${won(g.amount)}`}
              style={{ width: `${(g.amount / whole) * 100}%`, background: g.color }}
              onMouseMove={(e) => show(e, body(g))} onFocus={(e) => showAt(e.currentTarget, body(g))} onBlur={hide}
              onClick={() => g.to && navigate(g.to)} />
          ))}
        </div>
        {node}
      </div>
      <ul className="legend">
        {segs.map((g) => (
          <li key={g.key}>
            <i style={{ background: g.color }} />
            {g.label} <span className={g.cls}>{won(g.amount)}</span>
            <span className="muted">· {percent(g.amount, income)}%</span>
          </li>
        ))}
      </ul>
    </>
  )
}
