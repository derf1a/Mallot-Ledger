/** 홈 — 이번 기간 지출 캘린더와 지출 내역. 날을 누르면 그날 거래, 아니면 최근 거래. 자세한 편집은 Spending 화면에서 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ledgerApi } from '../ledger/api'
import Calendar from '../ledger/Calendar'
import { shortDate, won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'

const RECENT = 8

export default function SpendCalendar({ on }: { on?: string }) {
  const { data, error } = useLoad(() => ledgerApi.transactions(on), [on])
  const [day, setDay] = useState<string | null>(null)
  if (error) return <p className="error small">{error}</p>
  if (!data?.period) return <p className="muted small">불러오는 중…</p>
  const spend = data.transactions.filter((t) => t.type === 'expense' || (t.type === 'transfer' && t.transfer_kind === 'external'))
  const rows = (day ? data.transactions.filter((t) => t.occurred_on === day) : [...spend].sort((a, b) =>
    (b.occurred_on + (b.occurred_time ?? '')).localeCompare(a.occurred_on + (a.occurred_time ?? '')))).slice(0, day ? 50 : RECENT)
  const dayOut = day ? rows.filter((t) => t.type !== 'income' && t.type !== 'refund' && t.transfer_kind !== 'internal').reduce((s, t) => s + t.amount, 0) : 0
  return (
    <div className="home-calendar">
      <Calendar period={data.period} transactions={data.transactions} selected={day} onSelect={setDay} />
      <div className="home-calendar-list">
        <h3 className="small">
          {day ? <>{shortDate(day)} · 나간 돈 {won(dayOut)} <button className="link-button small" onClick={() => setDay(null)}>최근 보기</button></> : '최근 지출'}
        </h3>
        {rows.length === 0 ? (
          <p className="muted small">{day ? '이날 거래가 없어요' : '이번 기간 지출이 아직 없어요'}</p>
        ) : (
          <ul className="home-tx-list">
            {rows.map((t) => (
              <li key={t.id}>
                <span className="home-tx-icon" aria-hidden="true">{t.category_icon ?? t.recurring_icon ?? '•'}</span>
                <span className="home-tx-main">
                  <b>{t.merchant || '(이름 없음)'}</b>
                  <span className="muted small">{shortDate(t.occurred_on)} · {t.recurring_name ?? t.category_name ?? (t.type === 'income' ? '수입' : '미분류')}</span>
                </span>
                <span className={`num ${t.type === 'income' || t.type === 'refund' ? 'pos' : ''}`}>
                  {t.type === 'income' || t.type === 'refund' ? '+' : ''}{won(t.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Link to={day ? `/ledger?day=${day}` : '/ledger'} className="card-link small">지출 내역 전체 →</Link>
      </div>
    </div>
  )
}
