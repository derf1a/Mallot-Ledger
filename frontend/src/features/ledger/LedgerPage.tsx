import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ledgerApi, type Transaction, type TxQuery, type TxType } from './api'
import { budgetApi } from '../budget/api'
import { recurringApi } from '../recurring/api'
import Calendar from './Calendar'
import ImageImport from './ImageImport'
import PeriodNav from './PeriodNav'
import SourceBadge from './SourceBadge'
import TransactionForm from './TransactionForm'
import { longDate, parseISO, todayISO, won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'

/** 정기·저금 / 정기·지출 / 변동비 / 수입을 색으로 구분 */
function amountClass(t: Transaction) {
  if (t.transfer_kind === 'internal') return 'muted'
  if (t.type === 'income') return 'pos'
  if (t.type === 'refund') return 'amt-variable'
  if (t.recurring_kind) return t.recurring_kind === 'saving' ? 'amt-saving' : 'amt-fixed'
  return 'amt-variable'
}

function rowIcon(t: Transaction) {
  if (t.transfer_kind === 'internal') return '🔁'
  if (t.type === 'income') return '💵'
  if (t.type === 'refund') return '↩️'
  return t.recurring_icon || t.category_icon || '📌'
}

function amountText(t: Transaction) {
  if (t.transfer_kind === 'internal') return `±0 (${won(t.amount)})`
  return t.type === 'income' || t.type === 'refund' ? `+${won(t.amount)}` : `-${won(t.amount)}`
}

const PAGE = 300
const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토']

interface Filters {
  type?: TxType
  category_id?: string
  payment_method?: string
  needs_review?: boolean
  recurring?: 'linked' | 'unlinked'
  source?: 'manual' | 'image' | 'import'
}

const SCOPES: { value: number | 'period'; label: string }[] = [
  { value: 'period', label: '이번 기간' },
  { value: 3, label: '3개월' },
  { value: 6, label: '6개월' },
  { value: 12, label: '1년' },
  { value: 24, label: '2년' },
  { value: 0, label: '전체' },
]

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

export default function Ledger() {
  const { data: settings } = useLoad(() => ledgerApi.settings(), [])
  // 홈에서 넘어올 때: ?day=날짜(그날만) · ?category=id|none&on=날짜(그 기간의 그 카테고리) · ?review=1(분류 필요)
  const [params] = useSearchParams()
  const [on, setOn] = useState<string | undefined>(() => params.get('day') ?? params.get('on') ?? undefined)
  const [day, setDay] = useState<string | null>(() => params.get('day'))
  const [qInput, setQInput] = useState('')
  const q = useDebounced(qInput.trim(), 300)
  const [filters, setFilters] = useState<Filters>(() => ({
    category_id: params.get('category') ?? undefined,
    needs_review: params.get('review') ? true : undefined,
  }))
  const [showFilters, setShowFilters] = useState(false)
  // null = 설정의 검색 기본 범위. 홈에서 카테고리·분류 필요로 오면 그 기간만
  const [scope, setScope] = useState<number | 'period' | null>(() => (params.get('category') || params.get('review') ? 'period' : null))
  const [limit, setLimit] = useState(PAGE)
  const [addOpen, setAddOpen] = useState(false)
  const [editing, setEditing] = useState<Transaction | 'new' | null>(null)
  const [importFiles, setImportFiles] = useState<File[] | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const filterCount = Object.values(filters).filter((v) => v !== undefined && v !== '').length
  // 검색어나 필터가 있으면 '검색 모드': 한 달이 아니라 최근 N개월(설정, 기본 1년)에서 찾는다
  const searching = q !== '' || filterCount > 0
  const months = scope === 'period' ? undefined : (scope ?? settings?.search_months ?? 12)
  const query: TxQuery = searching
    ? scope === 'period'
      ? { on, q, ...filters, limit }
      : { q, months, ...filters, limit }
    : { on, limit: 5000 }
  const { data, error, reload } = useLoad(() => ledgerApi.searchTransactions(query), [JSON.stringify(query)])
  const { data: categories } = useLoad(() => budgetApi.categories(), [])
  const { data: recurringItems } = useLoad(() => recurringApi.recurringItems(), [])
  const { data: methods } = useLoad(() => ledgerApi.paymentMethods(), [])

  const all = data?.transactions ?? []
  const counted = all.filter((t) => t.transfer_kind !== 'internal')
  const totalIn = counted.filter((t) => t.type === 'income').reduce((a, t) => a + t.amount, 0)
  // 나간 돈: 지출 + 타 계좌 이체 (정산·환불은 들어온 돈이라 따로)
  const totalOut = counted.filter((t) => t.type === 'expense' || t.type === 'transfer').reduce((a, t) => a + t.amount, 0)
  const totalRefund = counted.filter((t) => t.type === 'refund').reduce((a, t) => a + t.amount, 0)
  const sumBy = (kind: 'saving' | 'expense') =>
    counted.filter((t) => t.recurring_kind === kind).reduce((a, t) => a + t.amount, 0)
  const totalSaving = sumBy('saving')
  const totalFixed = sumBy('expense')
  const reviewCount = all.filter((t) => t.needs_review).length

  const visible = all.filter((t) => !day || t.occurred_on === day)
  const today = todayISO()
  const byDate = new Map<string, Transaction[]>()
  for (const t of visible) byDate.set(t.occurred_on, [...(byDate.get(t.occurred_on) ?? []), t])

  const setFilter = <K extends keyof Filters>(k: K, v: Filters[K] | '') => {
    setFilters((f) => ({ ...f, [k]: v === '' ? undefined : v }))
    setLimit(PAGE)
  }
  const reset = () => {
    setQInput('')
    setFilters({})
    setScope(null)
    setLimit(PAGE)
  }
  const changePeriod = (next: string) => {
    setOn(next)
    setDay(null)
  }
  const done = () => {
    setEditing(null)
    setImportFiles(null)
    reload()
  }

  return (
    <section className="page ledger">
      <div className="page-header">
        <h1>가계부</h1>
        {!searching && <PeriodNav period={data?.period ?? undefined} onChange={changePeriod} />}
      </div>

      <div className="ledger-toolbar">
        <div className="search-box">
          <span aria-hidden="true">🔍</span>
          <input
            placeholder="가맹점·메모·카테고리·결제수단 검색"
            value={qInput}
            onChange={(e) => {
              setQInput(e.target.value)
              setLimit(PAGE)
            }}
            aria-label="거래 검색"
          />
          {qInput && (
            <button className="icon-button" aria-label="검색어 지우기" onClick={() => setQInput('')}>
              ✕
            </button>
          )}
        </div>
        <button className={`filter-toggle${filterCount ? ' on' : ''}`} aria-expanded={showFilters} onClick={() => setShowFilters((v) => !v)}>
          필터{filterCount ? ` ${filterCount}` : ''}
        </button>
        {/* 거래 추가: 우상단 — 누르면 캡쳐(앨범) 입력 / 직접 입력 */}
        <div className="add-menu">
          <button className="primary add-button" aria-haspopup="menu" aria-expanded={addOpen} onClick={() => setAddOpen((v) => !v)}>
            <span className="add-plus" aria-hidden="true">
              ＋
            </span>
            <span className="add-text">거래 추가</span>
            <span className="add-caret" aria-hidden="true">
              ▾
            </span>
          </button>
          {addOpen && (
            <>
              <div className="add-backdrop" onClick={() => setAddOpen(false)} />
              <div className="add-popover" role="menu">
                <button
                  role="menuitem"
                  onClick={() => {
                    setAddOpen(false)
                    fileInput.current?.click()
                  }}
                >
                  <span className="add-item-icon">📷</span>
                  <span>
                    <b>캡쳐로 입력</b>
                    <span className="muted small">결제 화면·앱 캡쳐를 AI가 읽어요</span>
                  </span>
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setAddOpen(false)
                    setEditing('new')
                  }}
                >
                  <span className="add-item-icon">✏️</span>
                  <span>
                    <b>직접 입력</b>
                    <span className="muted small">날짜·금액·가맹점을 직접 적어요</span>
                  </span>
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {showFilters && (
        <div className="filter-panel">
          <select value={filters.type ?? ''} onChange={(e) => setFilter('type', e.target.value as TxType | '')} aria-label="종류">
            <option value="">모든 종류</option>
            <option value="expense">지출</option>
            <option value="income">수입</option>
            <option value="transfer">이체</option>
            <option value="refund">정산·환불</option>
          </select>
          <select value={filters.category_id ?? ''} onChange={(e) => setFilter('category_id', e.target.value)} aria-label="카테고리">
            <option value="">모든 카테고리</option>
            <option value="none">미분류</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
          <select value={filters.payment_method ?? ''} onChange={(e) => setFilter('payment_method', e.target.value)} aria-label="결제수단">
            <option value="">모든 결제수단</option>
            {methods?.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} ({m.count})
              </option>
            ))}
          </select>
          <select
            value={filters.recurring ?? ''}
            onChange={(e) => setFilter('recurring', e.target.value as 'linked' | 'unlinked' | '')}
            aria-label="정기지출"
          >
            <option value="">정기지출 전체</option>
            <option value="linked">정기지출만</option>
            <option value="unlinked">정기지출 제외</option>
          </select>
          <select value={filters.source ?? ''} onChange={(e) => setFilter('source', e.target.value as Filters['source'] | '')} aria-label="입력 경로">
            <option value="">모든 입력 경로</option>
            <option value="manual">직접 입력</option>
            <option value="image">캡쳐</option>
            <option value="import">가져옴</option>
          </select>
          <label className="check small">
            <input type="checkbox" checked={!!filters.needs_review} onChange={(e) => setFilter('needs_review', e.target.checked || '')} />
            분류 필요만
          </label>
          {(filterCount > 0 || qInput) && (
            <button className="link small" onClick={reset}>
              모두 지우기
            </button>
          )}
        </div>
      )}

      {searching ? (
        <div className="search-summary">
          <div className="scope-chips" role="radiogroup" aria-label="검색 범위">
            {SCOPES.map((sc) => {
              const active = scope === sc.value || (scope === null && sc.value === (settings?.search_months ?? 12))
              return (
                <button key={String(sc.value)} role="radio" aria-checked={active} className={active ? 'on' : ''} onClick={() => setScope(sc.value)}>
                  {sc.label}
                </button>
              )
            })}
          </div>
          {data && (
            <span className="muted small">
              {data.range.start} ~ {data.range.end} · <b>{data.total.toLocaleString('ko-KR')}건</b> · 지출 {won(data.sums.expense)} · 수입 {won(data.sums.income)}
              {data.sums.transfer_out > 0 && ` · 타 계좌 이체 ${won(data.sums.transfer_out)}`}
              {data.sums.refund > 0 && ` · 정산·환불 +${won(data.sums.refund)}`}
            </span>
          )}
        </div>
      ) : (
        <div className="stat-row compact">
          <div>
            <span className="muted">수입</span>
            <strong className="pos">+{won(totalIn)}</strong>
          </div>
          <div>
            <span className="muted">정기 · 저금</span>
            <strong className="amt-saving">-{won(totalSaving)}</strong>
          </div>
          <div>
            <span className="muted">정기 · 지출</span>
            <strong className="amt-fixed">-{won(totalFixed)}</strong>
          </div>
          <div>
            <span className="muted">변동비</span>
            <strong className="amt-variable">-{won(totalOut - totalSaving - totalFixed - totalRefund)}</strong>
            {totalRefund > 0 && <span className="muted small">정산·환불 +{won(totalRefund)} 반영</span>}
          </div>
          {reviewCount > 0 && (
            <button
              className="chip-button"
              onClick={() => {
                setScope('period')
                setFilter('needs_review', true)
              }}
            >
              분류 필요 {reviewCount}건
            </button>
          )}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {/* 기간 보기에서는 항상 캘린더 → 그 아래 목록 (날짜를 누르면 그날만) */}
      {!searching && data?.period && (
        <Calendar period={data.period} transactions={all} selected={day} onSelect={setDay} />
      )}
      {day && (
        <p className="muted small">
          {longDate(day)} 거래만 보는 중 · <button className="link" onClick={() => setDay(null)}>전체 보기</button>
        </p>
      )}

      {data && visible.length === 0 && <p className="muted empty">{searching ? '조건에 맞는 거래가 없어요.' : '이 기간에 기록된 거래가 없어요.'}</p>}
      <div className="tx-list compact">
        {[...byDate.entries()].map(([date, items]) => {
          const isToday = date === today
          const dayOut = items.filter((t) => (t.type === 'expense' || t.type === 'transfer') && t.transfer_kind !== 'internal').reduce((a, t) => a + t.amount, 0)
          const dayIn = items.filter((t) => t.type === 'income' || t.type === 'refund').reduce((a, t) => a + t.amount, 0)
          const d = parseISO(date)
          const dayTitle = [dayIn > 0 ? `수입 +${won(dayIn)}` : '', dayOut > 0 ? `지출 -${won(dayOut)}` : ''].filter(Boolean).join(' · ')
          return items.map((t, k) => (
            <button key={t.id} className={`tx-row${k === 0 ? ' day-first' : ''}${t.needs_review ? ' review' : ''}`} onClick={() => setEditing(t)}>
              {/* 날짜는 그날 첫 행에만 — 날짜 머리줄을 없애 한 화면에 더 많이 보이게 */}
              <span className={`tx-day-cell${isToday ? ' today' : ''}`} title={dayTitle}>
                {k === 0 && (
                  <>
                    {searching && d.getFullYear() !== new Date().getFullYear() && <span className="muted">{String(d.getFullYear()).slice(2)}.</span>}
                    {d.getMonth() + 1}.{d.getDate()} <span className="muted">{isToday ? '오늘' : WEEKDAY[d.getDay()]}</span>
                  </>
                )}
              </span>
              <span className="icon tx-icon">{rowIcon(t)}</span>
              <span className="tx-main">
                <span className="tx-merchant">{t.merchant || '(이름 없음)'}</span>
                <span className="tx-meta muted">
                  {[t.transfer_kind === 'internal' ? '내 계좌 이체' : t.recurring_name ? `정기 · ${t.recurring_name}` : t.type === 'refund' ? `정산·환불${t.category_name ? ` · ${t.category_name}` : ''}` : t.category_name, t.payment_method, t.occurred_time?.slice(0, 5)]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
              <span className="badges">
                {t.needs_review && <span className="badge warn">분류 필요</span>}
                {t.category_source && t.category_source !== 'user' && t.category_source !== 'import' && <SourceBadge source={t.category_source} />}
                {t.source === 'image' && <span className="badge">캡쳐</span>}
              </span>
              <span className={`tx-amount ${amountClass(t)}`}>{amountText(t)}</span>
            </button>
          ))
        })}
      </div>
      {data && data.total > all.length && (
        <button className="more-button" onClick={() => setLimit((l) => l + PAGE)}>
          더 보기 ({(data.total - all.length).toLocaleString('ko-KR')}건 남음)
        </button>
      )}

      {/* capture 속성이 없으면 폰에서 카메라 대신 앨범(사진 보관함)이 열린다 */}
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) setImportFiles(files)
          e.target.value = ''
        }}
      />

      {editing && categories && recurringItems && (
        <TransactionForm
          initial={editing === 'new' ? undefined : editing}
          categories={categories}
          recurringItems={recurringItems}
          onClose={() => setEditing(null)}
          onSaved={done}
        />
      )}
      {importFiles && categories && (
        <ImageImport files={importFiles} categories={categories} onClose={() => setImportFiles(null)} onSaved={done} />
      )}
    </section>
  )
}
