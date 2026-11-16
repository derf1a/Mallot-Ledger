/**
 * 변동비 관리 (가계부 > Budget) — 주수입에서 정기지출을 빼고 남은 돈(할당 가능액)을 변동비 카테고리마다 나눠 준다.
 * 위: 배정할 돈(또는 초과) 큰 숫자 + 할당 가능액 식 + 카테고리별 배정 막대(올리면 금액·비중·이번 기간 사용).
 * 아래: 카테고리마다 월 예산 입력, 이번 기간 사용(예산 대비 막대 · 오늘까지 위치 눈금), 참고값(지난 기간 · 최근 평균 — 누르면 그 금액으로).
 * 이번 기간 사용을 누르면 그 카테고리로 잡힌 거래가 펼쳐지고, 잘못 분류된 거래는 거기서 재분류한다 (budget/CategoryTransactions).
 * 바꾼 예산은 모아서 한 번에 저장한다. 카테고리 추가·이름·아이콘·설명·삭제도 여기서 (예전 설정 > 가계부설정).
 */
import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { budgetApi, type BudgetCategory, type BudgetOverview } from './api'
import CategoryTransactions from './CategoryTransactions'
import Bar from '../../shared/ui/Bar'
import IconPicker from '../../shared/ui/IconPicker'
import { useTip } from '../../shared/ui/useTip'
import { percent, won } from '../../shared/format'
import { progress } from '../home/model'
import { categoryColor, compact } from '../insights/format'
import { useLoad } from '../../shared/useLoad'

/** 참고값을 예산으로 쓸 때: 1만 원 미만은 천 원, 그 위는 만 원 단위로 올림 */
const roundUp = (v: number) => (v <= 0 ? 0 : v < 10_000 ? Math.ceil(v / 1_000) * 1_000 : Math.ceil(v / 10_000) * 10_000)

export default function Budget() {
  const { data, error, reload } = useLoad(() => budgetApi.budget(), [])
  // 바꾸는 중인 예산 (카테고리 id → 금액). 저장한 값과 같으면 바뀐 것으로 치지 않는다
  const [drafts, setDrafts] = useState<Record<number, number>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  // 거래를 펼친 카테고리 (id, 'none' = 미분류)
  const [open, setOpen] = useState<number | 'none' | null>(null)

  const changed = data?.categories.filter((c) => drafts[c.id] !== undefined && drafts[c.id] !== c.budget) ?? []
  useEffect(() => {
    if (!changed.length) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault() // 저장하지 않고 나가려 하면 브라우저가 묻는다
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [changed.length])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted">불러오는 중…</p>

  const budgetOf = (c: BudgetCategory) => drafts[c.id] ?? c.budget
  const assigned = data.categories.reduce((a, c) => a + budgetOf(c), 0)
  const left = data.pool - assigned
  const order = data.categories.map((c) => c.name)
  const pg = progress(data.period, data.today)
  const flash = (text: string) => {
    setMessage(text)
    setTimeout(() => setMessage(null), 2500)
  }
  const setDraft = (id: number, v: number) => setDrafts((d) => ({ ...d, [id]: v }))
  const fill = (pick: (c: BudgetCategory) => number | null) =>
    setDrafts(Object.fromEntries(data.categories.map((c) => [c.id, roundUp(pick(c) ?? budgetOf(c))])))
  const save = async () => {
    setSaving(true)
    try {
      await budgetApi.saveBudgets(changed.map((c) => ({ id: c.id, budget: drafts[c.id] })))
      reload() // 저장한 값이 바뀐 값과 같아져 '바뀐 것'이 사라진다
      flash('예산을 저장했어요')
    } catch (e) {
      flash((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const hasAverage = data.categories.some((c) => c.average !== null)
  const toggle = (k: number | 'none') => setOpen((o) => (o === k ? null : k))
  const panel = (c: BudgetCategory | null) => (
    <CategoryTransactions category={c} categories={data.categories} period={data.period} today={data.today} onChanged={reload} />
  )

  return (
    <section className="page budget-page">
      <div className="page-header">
        <h1>변동비 관리</h1>
      </div>

      <article className="card bud-top">
        <div className="bud-figure">
          <span className="muted">{left >= 0 ? '배정할 돈' : '할당 가능액보다 더 배정했어요'}</span>
          <strong className={`hero-number${left < 0 ? ' neg' : ''}`}>{left < 0 ? `−${won(-left)}` : won(left)}</strong>
          <span className="small">
            할당 가능 <b className="amt-variable">{won(data.pool)}</b>
            <span className="muted">
              {' '}= 주수입 {won(data.income)} − 정기지출 {won(data.recurring_total)} ·{' '}
            </span>
            <Link to="/ledger/recurring">정기지출 보기</Link>
          </span>
          {data.income === 0 && (
            <span className="muted small">
              <Link to="/settings">설정 &gt; 개인설정</Link>에서 월 주수입을 넣으면 할당 가능액이 계산돼요.
            </span>
          )}
        </div>
        <AllocBar data={data} budgetOf={budgetOf} order={order} assigned={assigned} />
        <div className="bud-fill">
          <span className="muted small">참고값으로 한 번에 채우기 (만 원 단위로 올림, 저장 전까지는 바뀌지 않아요)</span>
          <div className="bud-fill-buttons">
            <button onClick={() => fill((c) => c.last)}>지난 기간 사용액 ({data.reference.last})</button>
            <button disabled={!hasAverage} onClick={() => fill((c) => c.average)}
              title={hasAverage ? `${data.reference.periods.join(', ')} 평균 · 100만 원 이상 한 건은 뺌` : '평균을 낼 만큼 지난 데이터가 없어요'}>
              최근 {data.reference.periods.length || 3}개 기간 평균
            </button>
          </div>
        </div>
      </article>

      <article className="card">
        <div className="bud-head" aria-hidden>
          <span>카테고리</span>
          <span>월 예산</span>
          <span>이번 기간 · 누르면 거래</span>
          <span>참고 · 누르면 그 금액으로</span>
        </div>
        {data.categories.map((c) => (
          <Fragment key={c.id}>
            <CategoryRow c={c} budget={budgetOf(c)} changed={changed.includes(c)} color={categoryColor(c.name, order)}
              pool={data.pool} pace={pg.current ? pg.ratio : undefined} lastLabel={data.reference.last} periods={data.reference.periods}
              open={open === c.id} onToggle={() => toggle(c.id)}
              onBudget={(v) => setDraft(c.id, v)} onSaved={reload} flash={flash} />
            {open === c.id && panel(c)}
          </Fragment>
        ))}
        {(data.uncategorized.count > 0 || data.uncategorized.last !== 0) && (
          <div className={`bud-row bud-none${open === 'none' ? ' open' : ''}`}>
            <div className="bud-name">
              <i className="swatch" style={{ background: 'var(--series-other)' }} />
              <span className="icon">❔</span>
              <span className="bud-title">
                <b>미분류</b>
                <span className="muted small">예산 없음 — 분류하면 그 카테고리 예산에서 빠져요</span>
              </span>
            </div>
            <div className="bud-input muted small">–</div>
            <UsageButton count={data.uncategorized.count} open={open === 'none'} onToggle={() => toggle('none')}>
              {won(data.uncategorized.spent)} 사용
            </UsageButton>
            <div className="bud-refs">
              {data.uncategorized.count > 0 && (
                <button className="small" aria-expanded={open === 'none'} onClick={() => toggle('none')}>
                  {open === 'none' ? '접기' : '분류하기'}
                </button>
              )}
            </div>
          </div>
        )}
        {open === 'none' && panel(null)}
        {adding ? (
          <NewCategory onDone={(ok) => {
            setAdding(false)
            if (ok) {
              reload()
              flash('카테고리를 추가했어요')
            }
          }} />
        ) : (
          <button className="bud-add" onClick={() => setAdding(true)}>+ 카테고리 추가</button>
        )}
      </article>

      {(changed.length > 0 || message) && (
        <div className="bud-save" role="status">
          {changed.length > 0 ? (
            <>
              <span>
                바꾼 예산 <b>{changed.length}</b>개 · 배정 <b className="num">{won(assigned)}</b>
                <span className="muted"> / 할당 가능 {won(data.pool)}</span>
              </span>
              <span className="bud-save-buttons">
                <button onClick={() => setDrafts({})} disabled={saving}>되돌리기</button>
                <button className="primary" onClick={save} disabled={saving}>{saving ? '저장 중…' : '저장'}</button>
              </span>
            </>
          ) : (
            <span>{message}</span>
          )}
        </div>
      )}
    </section>
  )
}

/** 카테고리별 배정 — 가로 100% 막대(할당 가능액 기준) + 범례. 더 배정했으면 막대가 넘친 만큼 한도 눈금을 그린다 */
function AllocBar({ data, budgetOf, order, assigned }: {
  data: BudgetOverview
  budgetOf: (c: BudgetCategory) => number
  order: string[]
  assigned: number
}) {
  const { box, show, showAt, hide, node } = useTip()
  const whole = Math.max(data.pool, assigned, 1)
  const free = Math.max(data.pool - assigned, 0)
  const segs = data.categories.filter((c) => budgetOf(c) > 0)
  const body = (c: BudgetCategory): ReactNode => (
    <>
      <b>{c.icon} {c.name}</b>
      <span className="viz-tip-row">
        <i className="viz-tip-key" style={{ background: categoryColor(c.name, order) }} />
        <strong className="num">{won(budgetOf(c))}</strong>
        <span className="muted">할당 가능액의 {percent(budgetOf(c), data.pool)}%</span>
      </span>
      <span className="muted">이번 기간 {won(c.spent)} 사용 · 지난 기간 {won(c.last)}</span>
    </>
  )
  return (
    <div className="bud-alloc" ref={box} onMouseLeave={hide}>
      <div className="stack-bar tall" role="group" aria-label="카테고리별 배정">
        {segs.map((c) => (
          <button key={c.id} type="button" className="stack-seg" aria-label={`${c.name} ${won(budgetOf(c))}`}
            style={{ width: `${(budgetOf(c) / whole) * 100}%`, background: categoryColor(c.name, order) }}
            onMouseMove={(e) => show(e, body(c))} onFocus={(e) => showAt(e.currentTarget, body(c))} onBlur={hide} />
        ))}
        {free > 0 && (
          <button type="button" className="stack-seg free" aria-label={`미배정 ${won(free)}`} style={{ width: `${(free / whole) * 100}%` }}
            onMouseMove={(e) => show(e, <><strong className="num">{won(free)}</strong><span className="muted">아직 배정하지 않은 돈</span></>)}
            onBlur={hide} />
        )}
        {assigned > data.pool && data.pool > 0 && (
          <i className="bud-limit" style={{ left: `${(data.pool / whole) * 100}%` }} title={`할당 가능 ${won(data.pool)}`} />
        )}
      </div>
      {node}
      <ul className="legend">
        {segs.map((c) => (
          <li key={c.id}>
            <i style={{ background: categoryColor(c.name, order) }} />
            {c.icon} {c.name} <span className="num">{won(budgetOf(c))}</span>
            <span className="muted">· {percent(budgetOf(c), data.pool)}%</span>
          </li>
        ))}
        {free > 0 && (
          <li>
            <i style={{ background: 'var(--border)' }} />
            미배정 <span className="num">{won(free)}</span>
          </li>
        )}
      </ul>
    </div>
  )
}

/** 이번 기간 사용 — 누르면 그 카테고리 거래를 펼친다 */
function UsageButton({ count, bar, open, onToggle, children }: {
  count: number
  bar?: ReactNode
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <button type="button" className={`bud-usage${open ? ' open' : ''}`} aria-expanded={open} onClick={onToggle}
      disabled={count === 0} title={count ? (open ? '거래 접기' : '이번 기간 거래 보기') : '이번 기간 거래가 없어요'}>
      {bar}
      <span className="bud-usage-line small">
        <span>{children}</span>
        {count > 0 && <span className="bud-usage-count">{count}건 {open ? '▴' : '▾'}</span>}
      </span>
    </button>
  )
}

/** 금액 입력 — 쉼표를 넣어 보여 주고 숫자만 받는다 */
function MoneyInput({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  return (
    <span className="money-input">
      <input inputMode="numeric" aria-label={label} placeholder="0" value={value ? value.toLocaleString('ko-KR') : ''}
        onChange={(e) => onChange(Number(e.target.value.replace(/[^0-9]/g, '')) || 0)} />
      <span className="muted">원</span>
    </span>
  )
}

function CategoryRow({ c, budget, changed, color, pool, pace, lastLabel, periods, open, onToggle, onBudget, onSaved, flash }: {
  c: BudgetCategory
  budget: number
  changed: boolean
  color: string
  pool: number
  pace: number | undefined
  lastLabel: string
  periods: string[]
  open: boolean
  onToggle: () => void
  onBudget: (v: number) => void
  onSaved: () => void
  flash: (text: string) => void
}) {
  const [edit, setEdit] = useState<{ name: string; icon: string; description: string } | null>(null)
  const saveInfo = async () => {
    if (!edit) return
    try {
      // 예산은 저장된 값 그대로 (바꾸는 중인 예산은 아래 저장 막대로)
      await budgetApi.updateCategory(c.id, { ...edit, budget: c.budget, sort_order: c.sort_order })
      setEdit(null)
      onSaved()
    } catch (e) {
      flash((e as Error).message)
    }
  }
  const remove = async () => {
    if (!confirm(`'${c.name}' 카테고리를 삭제할까요? 이 카테고리의 거래는 미분류가 돼요.`)) return
    try {
      await budgetApi.deleteCategory(c.id)
      onSaved()
      flash('삭제했어요')
    } catch (e) {
      flash((e as Error).message)
    }
  }

  return (
    <div className={`bud-row${changed ? ' changed' : ''}${open ? ' open' : ''}`}>
      {edit ? (
        <div className="bud-name bud-edit">
          <IconPicker value={edit.icon} onChange={(icon) => setEdit({ ...edit, icon })} />
          <input className="w-name" value={edit.name} aria-label="카테고리 이름" onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          <input className="w-desc" value={edit.description} placeholder="설명" aria-label="설명"
            onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
          <span className="bud-edit-buttons">
            <button className="primary" disabled={!edit.name.trim()} onClick={saveInfo}>저장</button>
            <button onClick={() => setEdit(null)}>취소</button>
            {!c.is_system && <button className="danger-text" onClick={remove}>삭제</button>}
          </span>
        </div>
      ) : (
        <div className="bud-name">
          <i className="swatch" style={{ background: color }} />
          <span className="icon">{c.icon}</span>
          <span className="bud-title">
            <b>{c.name}</b>
            {c.description && <span className="muted small">{c.description}</span>}
          </span>
          <button className="link bud-edit-link" onClick={() => setEdit({ name: c.name, icon: c.icon, description: c.description })}>편집</button>
        </div>
      )}
      <div className="bud-input">
        <MoneyInput value={budget} onChange={onBudget} label={`${c.name} 월 예산`} />
        <span className="muted small">{pool > 0 && budget > 0 ? `${percent(budget, pool)}%` : ''}</span>
      </div>
      <UsageButton count={c.count} open={open} onToggle={onToggle}
        bar={budget > 0 && <Bar value={c.spent} max={budget} tone="variable" pace={pace} />}>
        {won(c.spent)} 사용
        {budget > 0 && (
          <span className={c.spent > budget ? 'neg' : 'muted'}>
            {' '}· {c.spent > budget ? `${won(c.spent - budget)} 초과` : `${won(budget - c.spent)} 남음`}
          </span>
        )}
      </UsageButton>
      <div className="bud-refs">
        <button className="ref-chip" title={`지난 기간(${lastLabel}) ${won(c.last)} — 누르면 ${won(roundUp(c.last))}로`}
          onClick={() => onBudget(roundUp(c.last))}>
          지난 <b className="num">{compact(c.last)}</b>
        </button>
        {c.average !== null && (
          <button className="ref-chip"
            title={`${periods.map((p, i) => `${p} ${won(c.history[i])}`).join(' · ')} — 평균 ${won(c.average)}, 누르면 ${won(roundUp(c.average))}로`}
            onClick={() => onBudget(roundUp(c.average ?? 0))}>
            평균 <b className="num">{compact(c.average)}</b>
          </button>
        )}
      </div>
    </div>
  )
}

function NewCategory({ onDone }: { onDone: (ok: boolean) => void }) {
  const [c, setC] = useState({ name: '', icon: '', description: '', budget: 0 })
  const [error, setError] = useState<string | null>(null)
  const add = async () => {
    try {
      await budgetApi.createCategory({ ...c, name: c.name.trim(), sort_order: 99 })
      onDone(true)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <div className="bud-row bud-new">
      <div className="bud-name bud-edit">
        <IconPicker value={c.icon} onChange={(icon) => setC({ ...c, icon })} />
        <input className="w-name" placeholder="새 카테고리" value={c.name} aria-label="새 카테고리 이름" autoFocus
          onChange={(e) => setC({ ...c, name: e.target.value })} />
        <input className="w-desc" placeholder="설명" value={c.description} aria-label="설명" onChange={(e) => setC({ ...c, description: e.target.value })} />
      </div>
      <div className="bud-input">
        <MoneyInput value={c.budget} onChange={(budget) => setC({ ...c, budget })} label="새 카테고리 월 예산" />
      </div>
      <div className="bud-edit-buttons">
        <button className="primary" disabled={!c.name.trim()} onClick={add}>추가</button>
        <button onClick={() => onDone(false)}>취소</button>
        {error && <span className="neg small">{error}</span>}
      </div>
    </div>
  )
}
