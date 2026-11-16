import { useState } from 'react'
import type { Category } from '../budget/api'
import { ledgerApi, type MerchantRule, type Transaction, type TransactionInput, type TxType } from './api'
import type { RecurringItem } from '../recurring/api'
import { todayISO } from '../../shared/format'
import Modal from '../../shared/ui/Modal'

interface Props {
  initial?: Transaction
  categories: Category[]
  recurringItems: RecurringItem[]
  onClose: () => void
  onSaved: () => void
}

const TYPE_LABELS: Record<TxType, string> = { expense: '지출', income: '수입', transfer: '이체', refund: '정산·환불' }

export default function TransactionForm({ initial, categories, recurringItems, onClose, onSaved }: Props) {
  const [tx, setTx] = useState<TransactionInput>(
    initial ?? {
      occurred_on: todayISO(),
      type: 'expense',
      transfer_kind: null,
      amount: 0,
      merchant: '',
      category_id: null, // 비워 두면 가맹점 규칙으로 자동 분류
      category_source: null,
      recurring_id: null,
      payment_method: '',
      memo: '',
      source: 'manual',
    },
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rule, setRule] = useState<MerchantRule | null>(null)

  const set = <K extends keyof TransactionInput>(key: K, value: TransactionInput[K]) =>
    setTx((prev) => ({ ...prev, [key]: value }))

  const setType = (type: TxType) =>
    setTx((prev) => ({
      ...prev,
      type,
      transfer_kind: type === 'transfer' ? 'external' : null,
      category_id: type === 'expense' || type === 'refund' ? prev.category_id : null,
      category_source: type === 'expense' || type === 'refund' ? prev.category_source : null,
    }))

  // 가맹점을 입력하면 내 규칙으로 카테고리를 미리 골라 둔다
  const suggest = async (merchant: string) => {
    // 비어 있거나 규칙이 채운 카테고리만 바꾼다 — 기존 거래의 분류(출처가 없거나 AI)를 가맹점 칸 포커스만으로 덮어쓰지 않도록
    const replaceable = tx.category_id === null || tx.category_source === 'rule'
    if (!replaceable || !merchant.trim()) return
    const found = await ledgerApi.suggestRule(merchant).catch(() => null)
    setRule(found)
    if (found) setTx((p) => ({ ...p, category_id: found.category_id, category_source: 'rule' }))
    else if (tx.category_source === 'rule') setTx((p) => ({ ...p, category_id: null, category_source: null }))
  }

  const pickCategory = (id: number | null) =>
    setTx((p) => ({ ...p, category_id: id, category_source: id === null ? null : 'user' }))

  const internal = tx.type === 'transfer' && tx.transfer_kind === 'internal'
  const showCategory = tx.type === 'expense' || tx.type === 'refund' || (tx.type === 'transfer' && !internal)

  const save = async () => {
    if (tx.amount <= 0) return setError('금액을 입력하세요')
    setBusy(true)
    try {
      // 사용자가 카테고리를 직접 고른 이체는 '분류 필요'를 해제한다
      const body = { ...tx, reviewed: tx.category_id !== null }
      if (initial) {
        const saved = await ledgerApi.updateTransaction(initial.id, body)
        const n = saved.similar_count ?? 0
        const name = categories.find((c) => c.id === saved.category_id)?.name
        if (n > 0 && name && confirm(`같은 가맹점(${saved.merchant})의 다른 거래 ${n}건도 '${name}'(으)로 바꿀까요?`)) {
          await ledgerApi.applyRulePast(saved.merchant, saved.category_id!)
        }
      } else await ledgerApi.createTransaction(body)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!initial || !confirm('이 거래를 삭제할까요?')) return
    await ledgerApi.deleteTransaction(initial.id)
    onSaved()
  }

  return (
    <Modal title={initial ? '거래 수정' : '직접 입력'} onClose={onClose}>
      <div className="form">
        <div className="segmented" role="radiogroup" aria-label="종류">
          {(Object.keys(TYPE_LABELS) as TxType[]).map((t) => (
            <button key={t} role="radio" aria-checked={tx.type === t} className={tx.type === t ? 'on' : ''} onClick={() => setType(t)}>
              {TYPE_LABELS[t]}
            </button>
          ))}
        </div>

        {tx.type === 'refund' && (
          <p className="muted small">
            친구에게 1/n로 돌려받은 돈이나 환불이에요. 수입이 아니라 변동비에서 빠지고, 카테고리를 고르면 그 예산에서 차감돼요.
          </p>
        )}
        {tx.type === 'transfer' && (
          <label className="check">
            <input
              type="checkbox"
              checked={internal}
              onChange={(e) => setTx((p) => ({ ...p, transfer_kind: e.target.checked ? 'internal' : 'external', category_id: null }))}
            />
            내 계좌 간 이체 (합계에 반영 안 함, ±0)
          </label>
        )}

        <label>
          날짜
          <input type="date" value={tx.occurred_on} onChange={(e) => set('occurred_on', e.target.value)} />
        </label>
        <label>
          금액 (원)
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={tx.amount || ''}
            onChange={(e) => set('amount', Number(e.target.value))}
            autoFocus
          />
        </label>
        <label>
          {tx.type === 'income' ? '입금처' : tx.type === 'refund' ? '보낸 사람 / 환불한 곳' : tx.type === 'transfer' ? '받는 사람 / 계좌' : '가맹점'}
          <input value={tx.merchant} onChange={(e) => set('merchant', e.target.value)} onBlur={(e) => suggest(e.target.value)} />
        </label>

        {showCategory && (
          <label>
            카테고리
            <select
              value={tx.category_id ?? ''}
              onChange={(e) => pickCategory(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">
                {tx.type === 'transfer' ? '선택 안 함 (기타 · 분류 필요)' : tx.type === 'refund' ? '선택 안 함 (변동비 전체에서 차감)' : '자동 (내 규칙, 없으면 미분류)'}
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.icon} {c.name}
                </option>
              ))}
            </select>
            {tx.category_source === 'rule' && (
              <span className="muted small">🔁 {rule ? `'${rule.merchant_key}' 규칙` : '내 규칙'}으로 자동 선택됐어요</span>
            )}
            {tx.category_source === 'llm' && <span className="muted small">✨ AI가 고른 분류예요</span>}
          </label>
        )}

        {tx.type !== 'income' && tx.type !== 'refund' && !internal && (
          <label>
            정기지출 연결
            <select
              value={tx.recurring_id ?? ''}
              onChange={(e) => set('recurring_id', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">자동 (키워드·금액이 맞으면 연결)</option>
              {recurringItems.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.display_icon} {r.name} ({r.group_name})
                </option>
              ))}
            </select>
          </label>
        )}

        <label>
          결제수단
          <input value={tx.payment_method} placeholder="신한카드, 국민 월급통장 …" onChange={(e) => set('payment_method', e.target.value)} />
        </label>
        <label>
          메모
          <input value={tx.memo} onChange={(e) => set('memo', e.target.value)} />
        </label>

        {error && <p className="error">{error}</p>}
        <div className="form-actions">
          {initial && (
            <button className="danger-text" onClick={remove}>
              삭제
            </button>
          )}
          <button className="primary" disabled={busy} onClick={save}>
            저장
          </button>
        </div>
      </div>
    </Modal>
  )
}
