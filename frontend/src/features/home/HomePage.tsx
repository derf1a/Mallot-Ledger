/**
 * 홈 — 처음엔 숫자 하나와 그림 몇 개만, 자세한 건 마우스를 올리거나(터치는 누르기) 누르면 보인다.
 * 위에서부터: 할 일 칩 → 이번 달 남은 변동비(큰 숫자 + 누적 곡선) → 지출 캘린더 · 지출 내역 → 주수입 배분
 * → 변동비 예산 · 고정비 타임라인 → 최근 6개 기간 변동비 · 급여 · 소비 습관.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { homeApi, type HomeHistory, type HomeTrend } from './api'
import { ledgerApi, type Summary } from '../ledger/api'
import { recurringApi } from '../recurring/api'
import PeriodNav from '../ledger/PeriodNav'
import { percent, won } from '../../shared/format'
import Allocation from './Allocation'
import BudgetList from './BudgetList'
import SalaryCard from './SalaryCard'
import SpendCalendar from './SpendCalendar'
import { changeText, progress } from './model'
import RecurringTimeline from './RecurringTimeline'
import SpendCurve from './SpendCurve'
import { Columns } from '../insights/charts'
import { insightsApi } from '../insights/api'
import { useLoad } from '../../shared/useLoad'

export default function Home() {
  const [on, setOn] = useState<string>()
  const { data: s, error } = useLoad(() => ledgerApi.summary(on), [on])
  const { data: trend } = useLoad(() => homeApi.home(on).catch(() => null), [on])
  const { data: settings } = useLoad(() => ledgerApi.settings(), [])
  const { data: candidates } = useLoad(() => recurringApi.recurringCandidates(), [])
  const { data: reports } = useLoad(() => insightsApi.reports().catch(() => []), [])
  const lastReport = reports?.find((r) => r.status === 'succeeded')

  if (error) return <p className="error">{error}</p>

  const todos = s
    ? [
        s.needs_review > 0 && { to: '/ledger?review=1', tone: 'warn', label: '분류 필요', count: s.needs_review,
          title: '카테고리를 골라야 하는 이체가 있어요' },
        s.recurring.missed > 0 && { to: '/ledger/recurring', tone: 'danger', label: '미확인 정기지출', count: s.recurring.missed,
          title: s.recurring.items.filter((i) => i.status === 'missed').map((i) => `${i.name} ${won(i.amount)}`).join(', ') },
        !!candidates?.pending.length && { to: '/ledger/recurring', tone: 'info', label: '반복 지출 제안', count: candidates.pending.length,
          title: candidates.pending.map((c) => `${c.merchant} ${won(c.amount)}`).join(', ') },
      ].filter((t) => !!t)
    : []

  return (
    <section className="page home">
      <div className="page-header">
        <h1>{settings ? `${settings.owner_name}님의 이번 달` : '홈'}</h1>
        <PeriodNav period={s?.period} onChange={setOn} />
      </div>

      {todos.length > 0 && (
        <div className="todo-row">
          {todos.map((t) => (
            <Link key={t.label} to={t.to} className={`todo-chip ${t.tone}`} title={t.title}>
              {t.label} <b>{t.count}</b>
            </Link>
          ))}
        </div>
      )}

      {s && <Hero s={s} trend={trend} />}

      {s && (
        <div className="home-grid">
          <article className="card home-span-6">
            <h2>
              지출 캘린더 <Link to="/ledger" className="card-link">지출 내역 →</Link>
            </h2>
            <SpendCalendar on={on} />
          </article>

          <article className="card home-span-6">
            <h2>주수입 배분</h2>
            {s.income.planned === 0 ? (
              <p className="muted">
                <Link to="/settings">설정 &gt; 개인설정</Link>에서 월 주수입을 입력하면 배분을 볼 수 있어요.
              </p>
            ) : (
              <Allocation s={s} />
            )}
          </article>

          <article className="card home-span-3">
            <h2>
              변동비 예산 <Link to="/ledger/budget" className="card-link">예산 →</Link>
            </h2>
            <BudgetList s={s} trend={trend} />
          </article>

          <article className="card home-span-3">
            <h2>
              고정비 <Link to="/ledger/recurring" className="card-link">자세히 →</Link>
            </h2>
            <RecurringTimeline s={s} today={trend?.today ?? s.period.start} />
          </article>

          <article className="card home-span-2 home-history">
            <h2>최근 6개 기간 변동비</h2>
            {trend ? <History rows={trend.history} budget={s.variable.budget_total} /> : <p className="muted small">불러오는 중…</p>}
          </article>

          <article className="card home-span-2">
            <h2>
              급여 <Link to="/salary" className="card-link">급여 관리 →</Link>
            </h2>
            <SalaryCard />
          </article>

          <article className="card home-span-2">
            <h2>
              소비 습관 <Link to="/ledger/insights" className="card-link">분석 →</Link>
            </h2>
            {lastReport ? (
              <Link to={`/ledger/insights?report=${lastReport.id}`} className="habit-teaser">
                <b>{String(lastReport.summary?.title ?? '소비 습관 분석')}</b>
                {lastReport.summary?.headline ? <span>{String(lastReport.summary.headline)}</span> : null}
                <span className="muted small">
                  AI 분석 · {String(lastReport.summary?.window ?? '')} · {lastReport.created_at.slice(5, 10)}
                </span>
              </Link>
            ) : (
              <p className="muted small">
                AI가 가계부에서 요일·시간대·자주 가는 곳 같은 소비 습관을 찾아 줘요. <Link to="/ledger/insights">분석하러 가기</Link>
              </p>
            )}
          </article>
        </div>
      )}
    </section>
  )
}

/** 이번 달 남은 변동비 — 예산(없으면 변동비 가능액)에서 쓴 돈을 뺀 큰 숫자 하나 + 사실 몇 줄 + 누적 곡선 */
function Hero({ s, trend }: { s: Summary; trend: HomeTrend | null }) {
  const hasBudget = s.variable.budget_total > 0
  const basis = hasBudget ? s.variable.budget_total : Math.max(s.variable.pool, 0)
  const spent = s.variable.spent_total
  const left = basis - spent
  const pg = progress(s.period, trend?.today ?? s.period.start)

  let vsPrev: number | null = null
  if (trend && pg.elapsed > 0) {
    const i = pg.elapsed - 1
    const prevSoFar = trend.previous.daily.slice(0, i + 1).reduce((a, v) => a + v, 0)
    if (i < trend.previous.daily.length) vsPrev = spent - prevSoFar
  }
  const expected = Math.round(basis * pg.ratio)

  return (
    <article className="card home-hero">
      <div className="hero-figure">
        <span className="muted">{pg.current ? '이번 달 남은 변동비' : '이 기간 남은 변동비'}</span>
        <strong className={`hero-number${left < 0 ? ' neg' : ''}`}>{left < 0 ? `−${won(-left)}` : won(left)}</strong>
        <span className="hero-sub">
          {hasBudget ? '예산' : '변동비 가능액'} {won(basis)} 중 <b>{won(spent)}</b> 썼어요
          {basis > 0 && <span className="muted"> · {percent(spent, basis)}%</span>}
        </span>
        <ul className="hero-facts">
          {pg.current && left > 0 && pg.left > 0 && (
            <li>
              <span className="muted">남은 {pg.left}일 하루</span>
              <b className="num">{won(Math.floor(left / pg.left))}</b>
            </li>
          )}
          {pg.current && basis > 0 && (
            <li>
              <span className="muted">예산 속도보다</span>
              <b className={`num ${spent > expected ? 'neg' : 'pos'}`}>{won(Math.abs(spent - expected))} {spent > expected ? '더' : '덜'}</b>
            </li>
          )}
          {vsPrev !== null && (
            <li>
              <span className="muted">지난 기간 같은 날보다</span>
              <b className={`num ${vsPrev > 0 ? 'neg' : 'pos'}`}>{won(Math.abs(vsPrev))} {vsPrev > 0 ? '더' : '덜'}</b>
            </li>
          )}
          {!pg.current && trend && (
            <li>
              <span className="muted">{pg.elapsed === 0 ? '아직 시작 전인 기간' : '끝난 기간'}</span>
            </li>
          )}
        </ul>
      </div>
      <div className="hero-chart">{trend ? <SpendCurve trend={trend} budget={basis} /> : <div className="hero-chart-empty" />}</div>
    </article>
  )
}

function History({ rows, budget }: { rows: HomeHistory[]; budget: number }) {
  const cols = rows.map((h, i) => {
    const before = rows[i - 1]
    const change = before ? changeText(h.variable, before.variable) : null
    return {
      key: h.start,
      label: h.current ? '이번' : `${Number(h.start.slice(5, 7))}월`,
      segs: [{ key: 'v', name: '변동비', value: Math.max(h.variable, 0), color: 'var(--c-variable)' }],
      tip: (
        <>
          <b>{h.label}{h.current && ' · 진행 중'}</b>
          <span className="viz-tip-row">
            <i className="viz-tip-key" style={{ background: 'var(--c-variable)' }} />
            <strong className="num">{won(h.variable)}</strong>
            <span className="muted">변동비</span>
          </span>
          {change && <span className="muted">앞 기간보다 {change}</span>}
          {budget > 0 && <span className="muted">지금 예산 {won(budget)}의 {percent(h.variable, budget)}%</span>}
          <span className="muted">수입 {won(h.income)} · 정기지출 {won(h.recurring)}</span>
        </>
      ),
    }
  })
  return <Columns cols={cols} height={130} ariaLabel="최근 6개 기간 변동비" />
}
