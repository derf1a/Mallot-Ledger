import { useState, type ReactNode } from 'react'
import { recurringApi, type RecurringGroup, type RecurringItem, type RecurringItemInput } from './api'
import IconPicker from '../../shared/ui/IconPicker'
import Modal from '../../shared/ui/Modal'

interface Props {
  initial?: RecurringItem
  /** 처음 채울 값 (반복 지출 제안 등록 등). 주면 initial 대신 쓴다 */
  prefill?: RecurringItemInput
  title?: string
  /** 저장 동작 바꾸기 (기본: 항목 추가·수정 API). 주면 삭제 버튼은 숨긴다 */
  submit?: (r: RecurringItemInput) => Promise<void>
  /** 저장 버튼 위에 더 보여줄 내용 */
  children?: ReactNode
  groups: RecurringGroup[]
  onClose: () => void
  onSaved: () => void
}

/** 정기지출 항목 추가·수정 (정기지출 화면에서 사용) */
export default function RecurringForm({ initial, prefill, title, submit, children, groups, onClose, onSaved }: Props) {
  const [r, setR] = useState<RecurringItemInput>(
    prefill ??
    (initial
      ? {
          name: initial.name,
          group_id: initial.group_id,
          icon: initial.icon,
          amount: initial.amount,
          day_of_month: initial.day_of_month,
          match_keyword: initial.match_keyword,
          memo: initial.memo,
          active: initial.active,
          sort_order: initial.sort_order,
        }
      : { name: '', group_id: groups[0]?.id ?? 0, icon: '', amount: 0, day_of_month: null, match_keyword: '', memo: '', active: true, sort_order: 99 }),
  )
  const [error, setError] = useState<string | null>(null)
  const group = groups.find((g) => g.id === r.group_id)
  const set = <K extends keyof RecurringItemInput>(k: K, v: RecurringItemInput[K]) => setR((p) => ({ ...p, [k]: v }))

  const save = async () => {
    if (!r.name.trim()) return setError('항목 이름을 입력하세요')
    if (r.day_of_month !== null && (!Number.isInteger(r.day_of_month) || r.day_of_month < 1 || r.day_of_month > 31))
      return setError('출금일은 1~31 사이 숫자로 입력하거나 비워 두세요')
    try {
      if (submit) await submit(r)
      else if (initial) await recurringApi.updateRecurring(initial.id, r)
      else await recurringApi.createRecurring(r)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async () => {
    if (!initial || !confirm(`'${initial.name}' 항목을 삭제할까요? 연결된 가계부 거래는 남고 연결만 해제돼요.`)) return
    await recurringApi.deleteRecurring(initial.id)
    onSaved()
  }

  return (
    <Modal title={title ?? (initial ? '정기지출 수정' : '정기지출 추가')} onClose={onClose}>
      <div className="form">
        <div className="edit-row" style={{ border: 'none', padding: 0 }}>
          <IconPicker value={r.icon} fallback={group?.icon} onChange={(icon) => set('icon', icon)} />
          <input placeholder="항목 이름 (예: 넷플릭스)" value={r.name} onChange={(e) => set('name', e.target.value)} autoFocus />
        </div>
        <label>
          정기지출 카테고리
          <select value={r.group_id} onChange={(e) => set('group_id', Number(e.target.value))}>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.icon} {g.name} ({g.kind === 'saving' ? '저금' : '지출'})
              </option>
            ))}
          </select>
        </label>
        <label>
          금액 (원)
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={r.amount || ''}
            onChange={(e) => set('amount', Number(e.target.value))}
          />
        </label>
        <label>
          출금일 (매월 며칠)
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={31}
            placeholder="비우면 미정"
            value={r.day_of_month ?? ''}
            onChange={(e) => set('day_of_month', e.target.value === '' ? null : Number(e.target.value))}
          />
          <span className="muted small">
            {r.day_of_month === null
              ? '미정: 언제 나갈지 모르는 유동적인 지출이에요. 기간이 끝날 때까지는 미확인으로 표시하지 않아요.'
              : r.day_of_month > 28
                ? '그 날짜가 없는 달은 말일로 봐요.'
                : '비워 두면 출금일 미정으로 표시돼요.'}
          </span>
        </label>
        <label>
          매칭 키워드 (쉼표 구분)
          <input
            placeholder="가계부 거래의 가맹점·메모에 들어가는 글자"
            value={r.match_keyword}
            onChange={(e) => set('match_keyword', e.target.value)}
          />
        </label>
        <label>
          메모
          <input value={r.memo} onChange={(e) => set('memo', e.target.value)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={r.active} onChange={(e) => set('active', e.target.checked)} />
          사용 중 (끄면 집계와 미확인 알림에서 빠짐)
        </label>
        {children}
        {error && <p className="error">{error}</p>}
        <div className="form-actions">
          {initial && !submit && (
            <button className="danger-text" onClick={remove}>
              삭제
            </button>
          )}
          <button className="primary" onClick={save}>
            저장
          </button>
        </div>
      </div>
    </Modal>
  )
}
