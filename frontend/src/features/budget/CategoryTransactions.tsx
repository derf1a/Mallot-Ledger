/**
 * 변동비 관리에서 카테고리를 펼치면 보이는 이번 기간 거래 — 사용액과 같은 정의(variable)라 합계가 위 숫자와 맞는다.
 * 줄마다 날짜·가맹점·결제수단·분류 출처(내 규칙·AI)·금액, '재분류'로 다른 카테고리를 고르면 바로 옮긴다.
 * 옮긴 줄은 흐리게 남겨 두고(되돌리기 가능), 같은 가맹점의 다른 거래도 같이 바꿀지 묻는다. '수정'은 가계부의 거래 수정 창.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { budgetApi, type BudgetCategory, type Category } from './api'
import { ledgerApi, type Period, type Transaction } from '../ledger/api'
import { recurringApi, type RecurringItem } from '../recurring/api'
import SourceBadge from '../ledger/SourceBadge'
import TransactionForm from '../ledger/TransactionForm'
import { parseISO, periodLabel, won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'

const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토']
const LIMIT = 500

/** 받침이 있으면 '으로', 없거나 ㄹ 받침이면 '로' */
const ro = (word: string) => {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code < 11172 && code % 28 && code % 28 !== 8 ? '으로' : '로'
}

/** 변동비에서의 무게 — 정산·환불은 사용액을 줄인다 */
const signed = (t: Transaction) => (t.type === 'refund' ? -t.amount : t.amount)

interface Moved {
  to: number
  /** 같은 가맹점인데 카테고리가 다른 다른 거래 수 (지난 기간 포함) */
  similar: number
  /** 같은 가맹점 거래도 바꿨으면 바꾼 건수 */
  applied?: number
  /** 같은 가맹점 일괄 변경으로 같이 옮겨진 줄 */
  follow?: boolean
}

export default function CategoryTransactions({ category, categories, period, today, onChanged }: {
  /** null = 미분류 */
  category: BudgetCategory | null
  categories: BudgetCategory[]
  period: Period
  today: string
  onChanged: () => void
}) {
  const key = category ? String(category.id) : 'none'
  const { data, error, reload } = useLoad(
    () => ledgerApi.searchTransactions({ on: period.start, category_id: key, variable: true, limit: LIMIT }),
    [key, period.start],
  )
  const [sort, setSort] = useState<'date' | 'amount'>('date')
  const [picking, setPicking] = useState<number | null>(null)
  const [moved, setMoved] = useState<Record<number, Moved>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ tx: Transaction; categories: Category[]; recurring: RecurringItem[] } | null>(null)

  if (error) return <div className="bud-tx"><p className="error small">{error}</p></div>
  if (!data) return <div className="bud-tx"><p className="muted small">거래를 불러오는 중…</p></div>

  const byId = new Map(categories.map((c) => [c.id, c]))
  const rows = [...data.transactions]
  if (sort === 'amount') rows.sort((a, b) => signed(b) - signed(a))
  const staying = rows.filter((t) => !moved[t.id])
  const total = staying.reduce((a, t) => a + signed(t), 0)

  const move = async (t: Transaction, to: number) => {
    setBusy(t.id)
    setMessage(null)
    try {
      const saved = await ledgerApi.updateTransaction(t.id, { ...t, category_id: to, category_source: 'user', reviewed: true })
      setMoved((m) => {
        const next = { ...m }
        if (to === category?.id) delete next[t.id] // 원래 카테고리로 되돌림
        else next[t.id] = { to, similar: saved.similar_count ?? 0 }
        return next
      })
      setPicking(null)
      onChanged()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const applySimilar = async (t: Transaction, to: number) => {
    setBusy(t.id)
    try {
      const { updated } = await ledgerApi.applyRulePast(t.merchant, to)
      // 이 목록에서도 같은 가맹점 지출·이체는 같이 옮겨졌다 (정산·환불은 일괄 변경 대상이 아니다)
      setMoved((m) => {
        const next = { ...m, [t.id]: { ...m[t.id], applied: updated } }
        for (const r of data.transactions)
          if (r.id !== t.id && !next[r.id] && r.merchant_key === t.merchant_key && r.type !== 'refund')
            next[r.id] = { to, similar: 0, follow: true }
        return next
      })
      onChanged()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const edit = async (t: Transaction) => {
    try {
      const [cats, recurring] = await Promise.all([budgetApi.categories(), recurringApi.recurringItems()])
      setEditing({ tx: t, categories: cats, recurring })
    } catch (e) {
      setMessage((e as Error).message)
    }
  }

  const name = (id: number) => byId.get(id)?.name ?? '다른 카테고리'

  return (
    <div className="bud-tx" role="region" aria-label={`${category?.name ?? '미분류'} 이번 기간 거래`}>
      <div className="bud-tx-head">
        <span className="small">
          <b>{periodLabel(period)}</b>
          <span className="muted"> · {staying.length}건 · 합계 </span>
          <b className="num">{won(total)}</b>
          {staying.some((t) => t.type === 'refund') && <span className="muted"> (정산·환불 뺌)</span>}
        </span>
        <span className="bud-tx-tools">
          <span className="segmented small" role="group" aria-label="정렬">
            <button className={sort === 'date' ? 'on' : ''} aria-pressed={sort === 'date'} onClick={() => setSort('date')}>날짜순</button>
            <button className={sort === 'amount' ? 'on' : ''} aria-pressed={sort === 'amount'} onClick={() => setSort('amount')}>금액순</button>
          </span>
          <Link className="small" to={`/ledger?category=${key}&on=${period.start}`}>가계부에서 보기 →</Link>
        </span>
      </div>
      {!category && rows.length > 0 && (
        <p className="muted small">카테고리를 고르면 그 카테고리 예산에서 빠지고, 다음부터 같은 가맹점은 자동으로 분류돼요.</p>
      )}
      {message && <p className="error small">{message}</p>}
      {rows.length === 0 && <p className="muted small bud-tx-empty">이번 기간에 이 카테고리로 잡힌 거래가 없어요.</p>}

      <ul className="bud-tx-list">
        {rows.map((t) => {
          const m = moved[t.id]
          const d = parseISO(t.occurred_on)
          const current = m?.to ?? category?.id ?? null
          const meta = [
            t.type === 'refund' ? '정산·환불' : t.type === 'transfer' ? '송금' : '',
            t.payment_method,
            t.occurred_time?.slice(0, 5),
            t.memo,
          ].filter(Boolean)
          return (
            <li key={t.id} className={`bud-tx-row${m ? ' moved' : ''}${t.needs_review && !m ? ' review' : ''}`}>
              <span className={`bud-tx-date${t.occurred_on === today ? ' today' : ''}`}>
                {d.getMonth() + 1}.{d.getDate()} <span className="muted">{t.occurred_on === today ? '오늘' : WEEKDAY[d.getDay()]}</span>
              </span>
              <span className="bud-tx-main">
                <span className="bud-tx-merchant">{t.merchant || '(이름 없음)'}</span>
                {meta.length > 0 && <span className="muted bud-tx-meta">{meta.join(' · ')}</span>}
              </span>
              <span className="badges">
                {t.needs_review && !m && <span className="badge warn">분류 필요</span>}
                {/* 직접 고른 것·뱅크샐러드 분류는 가계부처럼 배지를 달지 않는다 (가져온 거래가 대부분이라 줄마다 붙으면 소음) */}
                {(t.category_source === 'rule' || t.category_source === 'llm') && !m && <SourceBadge source={t.category_source} />}
              </span>
              <span className={`bud-tx-amount num${t.type === 'refund' ? ' pos' : ''}`}>
                {t.type === 'refund' ? `+${won(t.amount)}` : won(t.amount)}
              </span>
              <span className="bud-tx-actions">
                {!m && (
                  <>
                    <button className={`small${picking === t.id ? ' on' : ''}`} aria-expanded={picking === t.id}
                      disabled={busy === t.id} onClick={() => setPicking(picking === t.id ? null : t.id)}>
                      {category ? '재분류' : '분류하기'}
                    </button>
                    <button className="link small" onClick={() => edit(t)}>수정</button>
                  </>
                )}
              </span>

              {picking === t.id && (
                <div className="bud-tx-sub bud-tx-pick" role="group" aria-label={`${t.merchant} 옮길 카테고리`}>
                  <span className="muted small">옮길 카테고리</span>
                  {categories.filter((c) => c.id !== current).map((c) => (
                    <button key={c.id} className="ref-chip" disabled={busy === t.id} onClick={() => move(t, c.id)}>
                      {c.icon} {c.name}
                    </button>
                  ))}
                  <button className="link small" onClick={() => setPicking(null)}>취소</button>
                </div>
              )}
              {m && (
                <div className="bud-tx-sub small">
                  <span>
                    → <b>{byId.get(m.to)?.icon} {name(m.to)}</b>{ro(name(m.to))} {m.follow ? '같이 ' : ''}옮겼어요
                  </span>
                  {category && !m.follow && (
                    <button className="link" disabled={busy === t.id} onClick={() => move(t, category.id)}>되돌리기</button>
                  )}
                  {!m.follow && m.similar > 0 && m.applied === undefined && (
                    <span className="bud-tx-similar">
                      <span className="muted">같은 가맹점({t.merchant})의 다른 거래 {m.similar}건도 바꿀까요? 지난 기간 포함</span>
                      <button className="small" disabled={busy === t.id} onClick={() => applySimilar(t, m.to)}>
                        모두 {name(m.to)}{ro(name(m.to))}
                      </button>
                    </span>
                  )}
                  {m.applied !== undefined && <span className="muted">같은 가맹점 거래 {m.applied}건도 바꿨어요</span>}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {data.total > data.transactions.length && (
        <p className="muted small">
          {data.total - data.transactions.length}건 더 있어요 · <Link to={`/ledger?category=${key}&on=${period.start}`}>가계부에서 모두 보기</Link>
        </p>
      )}

      {editing && (
        <TransactionForm initial={editing.tx} categories={editing.categories} recurringItems={editing.recurring}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            setMoved({})
            reload()
            onChanged()
          }} />
      )}
    </div>
  )
}
