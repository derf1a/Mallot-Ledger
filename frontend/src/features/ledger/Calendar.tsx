import type { Period, Transaction } from './api'
import { addDays, parseISO, todayISO } from '../../shared/format'

interface Props {
  period: Period
  transactions: Transaction[]
  selected: string | null
  onSelect: (day: string | null) => void
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

const compact = (n: number) => (n >= 10000 ? `${Math.round(n / 1000) / 10}만` : n.toLocaleString('ko-KR'))

/** 수입일 기준 기간을 주 단위 격자로 보여준다 */
export default function Calendar({ period, transactions, selected, onSelect }: Props) {
  const totals = new Map<string, { out: number; in: number }>()
  for (const t of transactions) {
    if (t.transfer_kind === 'internal') continue
    const d = totals.get(t.occurred_on) ?? { out: 0, in: 0 }
    if (t.type === 'income' || t.type === 'refund') d.in += t.amount
    else d.out += t.amount
    totals.set(t.occurred_on, d)
  }

  const today = todayISO()
  const cells: (string | null)[] = Array(parseISO(period.start).getDay()).fill(null)
  for (let d = period.start; d <= period.end; d = addDays(d, 1)) cells.push(d)

  return (
    <div className="calendar">
      {WEEKDAYS.map((w) => (
        <div key={w} className="cal-head">
          {w}
        </div>
      ))}
      {cells.map((day, i) => {
        if (!day) return <div key={`blank-${i}`} />
        const t = totals.get(day)
        const date = parseISO(day)
        return (
          <button
            key={day}
            className={`cal-cell${selected === day ? ' selected' : ''}${day === today ? ' today' : ''}`}
            onClick={() => onSelect(selected === day ? null : day)}
            aria-current={day === today ? 'date' : undefined}
          >
            <span className="cal-day">{date.getDate() === 1 || day === period.start ? `${date.getMonth() + 1}/${date.getDate()}` : date.getDate()}</span>
            {t && t.out > 0 && <span className="cal-out">-{compact(t.out)}</span>}
            {t && t.in > 0 && <span className="cal-in">+{compact(t.in)}</span>}
          </button>
        )
      })}
    </div>
  )
}
