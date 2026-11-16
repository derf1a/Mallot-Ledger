/**
 * 정기지출 타임라인 — 이번 기간(수입일 ~ 다음 수입일 전날)을 가로선 하나로 놓고 항목을 출금일 자리에 점으로 찍는다.
 * 색은 성격(저금 파랑·지출 주황), 모양은 상태(냈어요 = 채움 · 예정 = 테두리 · 미확인 = 빨강 + ! · 건너뜀 = 회색 테두리).
 * 같은 날 항목은 위로 쌓고, 점에 마우스를 올리면 금액·출금일·확인된 거래를 보여 준다. 날짜 미정 항목은 선 아래 칩으로.
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Summary } from '../ledger/api'
import type { RecurringStatusItem } from '../recurring/api'
import Bar from '../../shared/ui/Bar'
import { useTip } from '../../shared/ui/useTip'
import { longDate, shortDate, won } from '../../shared/format'
import { STATUS_LABEL, daysBetween, progress } from './model'

const STACK_GAP = 13

function body(i: RecurringStatusItem): ReactNode {
  return (
    <>
      <b>{i.display_icon} {i.name}</b>
      <span className="viz-tip-row">
        <i className="viz-tip-key" style={{ background: i.group_kind === 'saving' ? 'var(--c-saving)' : 'var(--c-fixed)' }} />
        <strong className="num">{won(i.amount)}</strong>
        <span className="muted">{i.group_name}</span>
      </span>
      <span className="muted">
        {i.due_date ? `${longDate(i.due_date)} · 매월 ${i.day_of_month}일` : '출금일 미정 — 기간 안 언제든'}
      </span>
      <span>
        {i.status === 'paid' && i.transaction
          ? `${shortDate(i.transaction.occurred_on)} ${i.transaction.merchant}로 ${i.early ? '미리 냈어요 (수입일 전)' : '냈어요'}`
          : i.status === 'missed'
            ? '예정일이 지났는데 확인된 거래가 없어요'
            : STATUS_LABEL[i.status]}
      </span>
    </>
  )
}

export default function RecurringTimeline({ s, today }: { s: Summary; today: string }) {
  const { box, show, showAt, hide, node } = useTip()
  const p = s.period
  const pg = progress(p, today)
  const span = Math.max(daysBetween(p.start, p.end), 1)
  const at = (d: string) => `${(daysBetween(p.start, d) / span) * 100}%`
  const items = s.recurring.items.filter((i) => i.status !== 'unset')
  const dated = items.filter((i) => i.due_date).sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))
  const floating = items.filter((i) => !i.due_date)
  const stackOf = new Map<number, number>()
  const seen = new Map<string, number>()
  for (const i of dated) {
    const k = i.due_date!
    stackOf.set(i.id, seen.get(k) ?? 0)
    seen.set(k, (seen.get(k) ?? 0) + 1)
  }
  const tallest = Math.max(0, ...seen.values())

  const counted = items.filter((i) => i.status !== 'skipped')
  const paid = counted.filter((i) => i.status === 'paid')
  const leftAmount = counted.filter((i) => i.status !== 'paid').reduce((a, i) => a + i.amount, 0)
  const next = dated.find((i) => i.status === 'upcoming')

  const dot = (i: RecurringStatusItem) => (
    <button key={i.id} type="button" className={`rt-dot ${i.group_kind} ${i.status}`} aria-label={`${i.name} ${won(i.amount)} ${STATUS_LABEL[i.status]}`}
      style={{ left: at(i.due_date!), bottom: (stackOf.get(i.id) ?? 0) * STACK_GAP }}
      onMouseMove={(e) => show(e, body(i))} onFocus={(e) => showAt(e.currentTarget, body(i))} onBlur={hide}>
      {i.status === 'missed' && <span aria-hidden>!</span>}
    </button>
  )

  return (
    <div ref={box} className="rt" onMouseLeave={hide}>
      <p className="rt-summary">
        <b className="num">{paid.length}</b>
        <span className="muted"> / {counted.length}건 냈어요</span>
        {leftAmount > 0 && <span> · 남은 <b className="num">{won(leftAmount)}</b></span>}
        {next?.due_date && (
          <span className="muted">
            {' '}· 다음 {next.display_icon} {next.name} {daysBetween(today, next.due_date) === 0 ? '오늘' : `${daysBetween(today, next.due_date)}일 뒤`}
          </span>
        )}
      </p>
      <div className="rt-track" style={{ paddingTop: 14 + tallest * STACK_GAP }} role="group" aria-label="정기지출 출금일">
        {pg.current && (
          <div className="rt-today" style={{ left: at(today) }}>
            <span>오늘</span>
          </div>
        )}
        <div className="rt-dots">
          <div className="rt-line" />
          {dated.map(dot)}
        </div>
        <div className="rt-axis">
          <span>{shortDate(p.start)}</span>
          <span>{shortDate(p.end)}</span>
        </div>
      </div>
      {floating.length > 0 && (
        <div className="rt-floating">
          <span className="muted small">날짜 미정</span>
          {floating.map((i) => (
            <button key={i.id} type="button" className={`rt-chip ${i.group_kind} ${i.status}`}
              onMouseMove={(e) => show(e, body(i))} onFocus={(e) => showAt(e.currentTarget, body(i))} onBlur={hide}>
              {i.display_icon} {i.name}
            </button>
          ))}
        </div>
      )}
      <ul className="rt-legend" aria-hidden>
        <li><i className="rt-key paid" />냈어요</li>
        <li><i className="rt-key upcoming" />예정</li>
        <li><i className="rt-key missed">!</i>미확인</li>
        <li><i className="rt-key skipped" />건너뜀</li>
        <li><i className="rt-key swatch saving" />저금</li>
        <li><i className="rt-key swatch expense" />지출</li>
      </ul>
      <div className="rt-groups">
        {s.recurring.groups.map((g) => (
          <Link key={g.group_id} to="/ledger/recurring" className="rt-group">
            <span className="rt-group-name">{g.icon} {g.group_name}</span>
            <Bar value={g.paid} max={g.amount} kind="progress" tone={g.kind === 'saving' ? 'saving' : 'fixed'} />
            <span className="num rt-group-amt">
              {won(g.paid)} <span className="muted">/ {won(g.amount)}</span>
            </span>
          </Link>
        ))}
      </div>
      {node}
    </div>
  )
}
