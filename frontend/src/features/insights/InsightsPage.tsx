/**
 * Insights (Ledger > Insights) — LLM 소비 습관 분석.
 * 한 줄 필터(분석 기간·모델·AI 분석) → 지표 타일 → AI 보고서(습관·제안·고정비·저금·절세·카테고리, 근거 사실 번호)
 * → 고정비·저금(주수입 배분·계획 vs 실제) → 절세(올해 공제 항목·내 정보) → 그림(기간별 카테고리·요일·시간대·많이 쓴 곳).
 * 숫자와 그림은 코드가 계산한 통계(/api/spending/stats, LLM 없이 바로), 해석은 작업(run) spending_report —
 * LLM 은 번호 붙은 사실만 근거로 쓰고, 목록에 없는 번호는 코드가 지운다.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { won } from '../../shared/format'
import { insightsApi, type Fact, type HabitTone, type Months, type Note, type SpendingFacts, type SpendingReport } from './api'
import { Columns, MerchantBars, TipRows, type Col } from './charts'
import FixedSaving from './FixedSaving'
import TaxCard from './TaxCard'
import { categoryColor, change, pct } from './format'
import { MODELS } from './format'
import { StatTile } from '../../shared/charts'
import { isActive, STATUS_LABEL, useRunLive } from '../runs/live'
import { useLoad } from '../../shared/useLoad'

const MONTHS: { key: Months; label: string }[] = [
  { key: 1, label: '1개월' },
  { key: 3, label: '3개월' },
  { key: 6, label: '6개월' },
  { key: 12, label: '12개월' },
]
const TONE: Record<HabitTone, string> = { good: '잘하고 있어요', neutral: '특징', watch: '살펴볼 점' }
const UNCATEGORIZED = '미분류'

const asMonths = (v: unknown): Months | null => ([1, 3, 6, 12] as number[]).includes(Number(v)) ? (Number(v) as Months) : null

export default function Insights() {
  const [params, setParams] = useSearchParams()
  const [months, setMonths] = useState<Months>(() => asMonths(params.get('months')) ?? 3)
  const [model, setModel] = useState('')
  const [selected, setSelected] = useState<number | null>(() => (params.get('report') ? Number(params.get('report')) : null))
  const [version, setVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { data, error: statsError, reload } = useLoad(() => insightsApi.stats(months), [months])
  const { data: runs } = useLoad(() => insightsApi.reports(), [version])
  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  const current = selected ?? runs?.[0]?.id ?? null
  const running = !!runs?.some((r) => isActive(r.status))

  const remember = (next: { months?: Months; report?: number }) =>
    setParams((p) => {
      const q = new URLSearchParams(p)
      if (next.months) q.set('months', String(next.months))
      if (next.report) q.set('report', String(next.report))
      return q
    }, { replace: true })
  const chooseMonths = (m: Months) => {
    setMonths(m)
    remember({ months: m })
  }
  const pick = (id: number, m: Months | null) => {
    setSelected(id)
    if (m) setMonths(m)
    remember({ report: id, months: m ?? undefined })
  }
  const start = async () => {
    setError(null)
    setBusy(true)
    try {
      const run = await insightsApi.createReport({ months, model })
      pick(run.id, months)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="page insights-page">
      <div className="page-header">
        <h1>소비 습관</h1>
        <span className="muted small">수입일 기준으로 끝난 기간을 봐요 · 숫자는 코드가 계산하고 해석은 AI가 해요</span>
      </div>

      <div className="insights-filters">
        <div className="segmented" role="tablist" aria-label="분석 기간">
          {MONTHS.map((m) => (
            <button key={m.key} role="tab" aria-selected={months === m.key} className={months === m.key ? 'on' : ''} onClick={() => chooseMonths(m.key)}>
              {m.label}
            </button>
          ))}
        </div>
        {data && (
          <span className="muted small">
            분석 {data.window.label}{data.baseline ? ` · 비교 ${data.baseline.label}` : ' · 비교 기간 없음'}
          </span>
        )}
        <span className="insights-run">
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="모델">
            {MODELS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
          <button className="primary" disabled={busy || running || !data} onClick={start}>
            {running ? 'AI 분석 중…' : 'AI 분석'}
          </button>
        </span>
      </div>
      {error && <p className="error small">{error}</p>}
      {statsError && <p className="alert warn">{statsError}</p>}
      {data?.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
      {!data && !statsError && <p className="muted">불러오는 중…</p>}

      {data && <Kpis f={data} />}

      <article className="card insights-report">
        <div className="section-head">
          <h2>AI 분석</h2>
          {runs && runs.length > 0 && (
            <div className="report-list">
              {runs.slice(0, 6).map((r) => (
                <button key={r.id} className={`report-pill${r.id === current ? ' on' : ''}`} onClick={() => pick(r.id, asMonths(r.params.months))}>
                  <span>{(r.summary?.title as string) ?? r.name}</span>
                  {isActive(r.status) || r.status !== 'succeeded' ? <span className={`chip run-${r.status}`}>{STATUS_LABEL[r.status]}</span> : null}
                  <span className="muted small">{asMonths(r.params.months) ?? '?'}개월 · {r.created_at.slice(5, 16)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {current === null ? (
          <div className="insights-empty">
            <p>가계부에서 코드가 숫자를 계산하고(요일·시간대·자주 가는 곳·예산 대비·고정비·저금·올해 절세 등), AI가 그 숫자만 근거로 소비 습관과 실천할 제안을 정리해요. 절세 금액은 AI가 아니라 코드가 계산해요.</p>
            <p className="muted small">위에서 기간을 고르고 'AI 분석'을 누르세요. 거래 내역 요약이 내 Claude 계정(로컬 Claude Code 로그인)으로 보내져요. 이체 상대 이름과 계좌번호처럼 보이는 이름은 보내지 않아요.</p>
          </div>
        ) : (
          <ReportView key={current} id={current} onDone={refresh} />
        )}
      </article>

      {data && (
        <div className="insights-grid">
          <FixedSaving f={data.stats.fixed} />
          <TaxCard t={data.stats.tax} onSaved={reload} />
        </div>
      )}

      {data && <Charts f={data} />}
    </section>
  )
}

function Kpis({ f }: { f: SpendingFacts }) {
  const k = f.stats.kpis
  const cur = f.stats.current
  const diff = change(k.avg_total, k.baseline_avg)
  return (
    <div className="tile-row insights-tiles">
      <StatTile label="기간 평균 변동비" value={won(k.avg_total)}
        hint={<>{diff ? `비교 기간 대비 ${diff}` : '비교 기간 없음'}{k.one_off_count ? ` · 일회성 큰 지출 ${k.one_off_count}건 제외` : ''}</>} />
      {cur && (
        <StatTile label={`이번 기간 ${cur.elapsed}일째`} value={won(cur.spent)}
          hint={`같은 날짜까지 평균 ${won(cur.pace)}${change(cur.spent, cur.pace) ? ` (${change(cur.spent, cur.pace)})` : ''}`} />
      )}
      <StatTile label="1만 원 미만 결제" value={pct(k.small_count_share)} hint={`결제 건수 기준 · 금액으로는 ${pct(k.small_amount_share)}`} />
      {k.night_share !== null && <StatTile label="밤 10시~새벽 4시" value={pct(k.night_share)} hint="결제 금액 중 비중" />}
      {k.payday_ratio !== null && <StatTile label="수입일 직후 7일" value={`${k.payday_ratio.toFixed(1)}배`} hint="나머지 날 하루 평균과 비교" />}
      {k.saving_rate !== null && <StatTile label="저금·투자 비율" value={pct(k.saving_rate)} hint="분석 기간 평균 ÷ 월 주수입" />}
      {k.tax_extra !== null && k.tax_extra > 0 && (
        <StatTile label="연말까지 더 줄일 세금" value={`약 ${won(k.tax_extra)}`} hint="절세 추정 · 아래 '절세'" />
      )}
    </div>
  )
}

function ReportView({ id, onDone }: { id: number; onDone: () => void }) {
  const { run, logs } = useRunLive(id)
  const finished = !!run && !isActive(run.status)
  const { data } = useLoad(() => (finished ? insightsApi.report(id) : Promise.resolve(null)), [id, finished])
  useEffect(() => {
    if (finished) onDone() // 목록의 상태·제목을 새로 고침
  }, [finished, onDone])
  if (!run) return <p className="muted small">불러오는 중…</p>
  if (isActive(run.status)) {
    return (
      <div className="card inner">
        <div className="run-progress">
          <span className="chip run-running">{STATUS_LABEL[run.status]}</span>
          <div className="progress-bar"><i style={{ width: `${Math.round(run.progress * 100)}%` }} /></div>
          <span className="muted small">{Math.round(run.progress * 100)}%</span>
        </div>
        <ul className="log-lines small">
          {logs.slice(-5).map((l) => <li key={l.id} className={l.level}>{l.message}</li>)}
        </ul>
      </div>
    )
  }
  if (run.status !== 'succeeded') return <p className="error small">분석 실패: {run.error}</p>
  const rep = data?.report
  return rep ? <Report rep={rep} runId={id} /> : <p className="muted small">보고서를 불러오는 중…</p>
}

function Report({ rep, runId }: { rep: SpendingReport; runId: number }) {
  const [focus, setFocus] = useState<number | null>(null)
  const byId = new Map(rep.facts.map((f) => [f.id, f]))
  useEffect(() => {
    if (focus !== null) document.getElementById(`fact-${runId}-${focus}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus, runId])
  const cites = (ids: number[]) =>
    ids.length ? (
      <span className="cites">
        {ids.map((i) => (
          <button key={i} className="cite" title={byId.get(i)?.text} onClick={() => setFocus(i)} aria-label={`근거 사실 ${i}`}>
            {i}
          </button>
        ))}
      </span>
    ) : (
      <span className="chip muted-chip" title="AI가 단 근거 번호가 사실 목록에 없어 지웠어요">근거 없음</span>
    )
  return (
    <div className="spending-report">
      <header>
        <h3>{rep.title}</h3>
        {rep.headline && <p className="report-headline">{rep.headline}</p>}
        <p className="muted small">
          분석 {rep.window.label} · 비교 {rep.baseline?.label ?? '없음'} · 근거 사실 {rep.facts.length}개
          {rep.citations_dropped > 0 && ` · 잘못된 근거 번호 ${rep.citations_dropped}개 제거`}
          {rep.ungrounded > 0 && ` · 근거 없는 항목 ${rep.ungrounded}개`} · 실행 #{runId}
        </p>
      </header>
      {rep.summary && <p>{rep.summary}</p>}

      {rep.habits.length > 0 && (
        <section>
          <h4>습관</h4>
          <NoteCards notes={rep.habits} cites={cites} />
        </section>
      )}

      {rep.suggestions.length > 0 && (
        <section>
          <h4>이렇게 해 보세요</h4>
          <ol className="suggestions">
            {rep.suggestions.map((s, k) => (
              <li key={k}>
                <div className="suggestion-head">
                  <b>{s.action}</b>
                  {s.monthly_saving > 0 && <span className="chip saving" title="AI가 사실의 숫자로 계산한 추정이에요">월 약 {won(s.monthly_saving)} 절감 (추정)</span>}
                </div>
                <p className="muted small">{s.reason} {cites(s.fact_ids)}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {(rep.money_notes?.length ?? 0) > 0 && (
        <section>
          <h4>고정비·저금</h4>
          <NoteCards notes={rep.money_notes!} cites={cites} />
        </section>
      )}

      {(rep.tax_tips?.length ?? 0) > 0 && (
        <section>
          <h4>절세 <span className="muted small">금액은 코드가 계산한 추정</span></h4>
          <ol className="suggestions">
            {rep.tax_tips!.map((t, k) => (
              <li key={k}>
                <div className="suggestion-head">
                  <span className="chip muted-chip">{t.title}</span>
                  <b>{t.action}</b>
                  {t.extra_saving > 0 && (
                    <span className="chip saving" title="코드가 세법 숫자로 계산한 추정이에요 (지방세 포함)">
                      {t.useful > 0 ? `${won(t.useful)} 더 내면 ` : ''}연 약 {won(t.extra_saving)} 절세
                    </span>
                  )}
                </div>
                <p className="muted small">{t.reason} {cites(t.fact_ids)}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {rep.category_notes.length > 0 && (
        <section>
          <h4>카테고리</h4>
          <ul className="category-notes">
            {rep.category_notes.map((c, k) => (
              <li key={k}><b>{c.category}</b> {c.note} {cites(c.fact_ids)}</li>
            ))}
          </ul>
        </section>
      )}

      {rep.questions.length > 0 && (
        <section>
          <h4>확인할 것</h4>
          <ul>{rep.questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </section>
      )}

      <details className="facts-list" open={focus !== null}>
        <summary className="muted small">근거 사실 {rep.facts.length}개 — 코드가 계산한 숫자 (AI에게 보낸 그대로)</summary>
        <ol>
          {rep.facts.map((f: Fact) => (
            <li key={f.id} id={`fact-${runId}-${f.id}`} className={focus === f.id ? 'on' : ''}>
              <span className="fact-id">{f.id}</span> {f.text}
            </li>
          ))}
        </ol>
      </details>
    </div>
  )
}

function NoteCards({ notes, cites }: { notes: Note[]; cites: (ids: number[]) => ReactNode }) {
  return (
    <div className="habit-cards">
      {notes.map((h, k) => (
        <div key={k} className={`habit ${h.tone}`}>
          <span className="habit-tone">{TONE[h.tone]}</span>
          <b>{h.title}</b>
          <p>{h.detail} {cites(h.fact_ids)}</p>
        </div>
      ))}
    </div>
  )
}

function DataTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <details className="table-view">
      <summary className="muted small">표로 보기</summary>
      <div className="scroll-x">
        <table className="data-table small">
          <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j} className="num">{c}</td>))}</tr>)}</tbody>
        </table>
      </div>
    </details>
  )
}

function Charts({ f }: { f: SpendingFacts }) {
  const s = f.stats
  const order = f.categories.map((c) => c.name)
  const names = [...order, UNCATEGORIZED].filter((n) => s.periods.some((p) => (p.by_category[n] ?? 0) > 0))
  const first = s.periods.findIndex((p) => p.in_window)
  const periodCols: Col[] = s.periods.map((p) => {
    const segs = names.map((n) => ({ key: n, name: n, value: Math.max(0, p.by_category[n] ?? 0), color: categoryColor(n, order) }))
    return {
      key: p.start, label: p.label.split('~')[0], segs,
      tip: <TipRows title={`${p.label}${p.in_window ? '' : ' (비교 기간)'}`} rows={[...segs].reverse().filter((x) => x.value > 0)}
        foot={<>합계 {won(p.total)}{p.one_off ? ` · 일회성 큰 지출 ${won(p.one_off)} 제외` : ''}</>} />,
    }
  })
  const weekdayCols: Col[] = s.weekday.map((w) => ({
    key: w.day, label: w.day, segs: [{ key: 'avg', name: '하루 평균', value: w.avg, color: 'var(--series-1)' }],
    tip: <TipRows title={`${w.day}요일`} rows={[{ name: '하루 평균', value: w.avg }]} foot={`합계 ${won(w.total)} · ${w.days}일`} />,
  }))
  const hourCols: Col[] | null = s.hours && s.hours.map((h) => ({
    key: String(h.hour), label: `${h.hour}시`, segs: [{ key: 'amount', name: '결제', value: h.amount, color: 'var(--series-1)' }],
    tip: <TipRows title={`${h.hour}시대`} rows={[{ name: '결제 합계', value: h.amount }]} foot={`${h.count}건`} />,
  }))

  return (
    <div className="insights-grid">
      <article className="card insights-wide">
        <h2>기간별 변동비 <span className="muted small">카테고리 · 일회성 큰 지출 제외</span></h2>
        <Columns cols={periodCols} bands={first >= 0 ? [{ start: first, end: s.periods.length - 1, label: '분석 기간' }] : []}
          ariaLabel="기간별 카테고리 변동비" />
        <ul className="bar-legend">
          {names.map((n) => <li key={n}><i className="swatch" style={{ background: categoryColor(n, order) }} />{n}</li>)}
        </ul>
        <DataTable head={['기간', ...names, '합계']}
          rows={s.periods.map((p) => [p.label + (p.in_window ? '' : ' (비교)'), ...names.map((n) => won(p.by_category[n] ?? 0)), won(p.total)])} />
      </article>

      <article className="card">
        <h2>요일별 하루 평균 결제</h2>
        <Columns cols={weekdayCols} height={150} ariaLabel="요일별 하루 평균 결제" />
        <DataTable head={['요일', '하루 평균', '합계', '날 수']} rows={s.weekday.map((w) => [w.day, won(w.avg), won(w.total), `${w.days}일`])} />
      </article>

      <article className="card">
        <h2>시간대별 결제 <span className="muted small">{hourCols ? `시각을 아는 결제 ${pct(s.hour_coverage)} 기준` : ''}</span></h2>
        {hourCols ? (
          <>
            <Columns cols={hourCols} height={150} labelEvery={3} ariaLabel="시간대별 결제 합계"
              bands={[{ start: 0, end: 4, label: '밤' }, { start: 22, end: 23, label: '밤' }]} />
            <DataTable head={['시', '결제 합계', '건수']} rows={s.hours!.filter((h) => h.count).map((h) => [`${h.hour}시`, won(h.amount), `${h.count}건`])} />
          </>
        ) : (
          <p className="muted small">결제 시각을 아는 거래가 절반이 안 돼서 시간대는 보지 않아요 (뱅크샐러드로 가져온 거래는 시각이 있어요).</p>
        )}
      </article>

      <article className="card">
        <h2>많이 쓴 곳 <span className="muted small">정기지출 제외 결제</span></h2>
        {s.merchants.length ? <MerchantBars items={s.merchants} /> : <p className="muted small">결제가 없어요.</p>}
      </article>
    </div>
  )
}
