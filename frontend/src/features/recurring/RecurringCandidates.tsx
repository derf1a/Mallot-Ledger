import { useState } from 'react'
import { recurringApi, type RecurringCandidate, type RecurringGroup, type RecurringItemInput } from './api'
import { shortDate, todayISO, won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'
import RecurringForm from './RecurringForm'

const WEEKDAYS = '월화수목금토일'

const cadenceLabel = (c: RecurringCandidate) =>
  c.cadence === 'monthly' ? `매월 ${c.anchor}일` : `매주 ${WEEKDAYS[c.anchor]}요일`

const confidenceLabel = (x: number) => (x >= 0.8 ? '높음' : x >= 0.6 ? '보통' : '낮음')

const dayLabel = (day: number | null) => (day ? `${day}일` : '미정')

/** 결제 기간: 매월은 '25.10~26.10'(해를 넘기면 같은 월끼리 헷갈리므로), 매주는 '6/6~6/27' */
function spanLabel(c: RecurringCandidate) {
  if (c.cadence === 'weekly') return `${shortDate(c.first_on)}~${shortDate(c.last_on)}`
  const ym = (iso: string) => `${iso.slice(2, 4)}.${Number(iso.slice(5, 7))}`
  return `${ym(c.first_on)}~${ym(c.last_on)}`
}

/** 기존 키워드 뒤에 붙인다 (이미 있으면 그대로) */
function appendKeyword(existing: string, keyword: string) {
  const parts = existing.split(',').map((k) => k.trim()).filter(Boolean)
  return parts.some((k) => k.toLowerCase() === keyword.toLowerCase()) ? existing : [...parts, keyword].join(', ')
}

type Opened = { c: RecurringCandidate; merge: boolean }

/** 기존 항목에 합칠 때 바뀌는 값: 키워드를 더하고, 금액·출금일은 실제 결제에 맞춘다 (자동 매칭은 금액이 같아야 함) */
function mergedItem(c: RecurringCandidate): RecurringItemInput {
  const s = c.similar_item!
  return {
    name: s.name,
    group_id: s.group_id,
    icon: s.icon,
    amount: c.amount,
    day_of_month: c.cadence === 'monthly' ? c.anchor : s.day_of_month,
    match_keyword: appendKeyword(s.match_keyword, c.keyword),
    memo: s.memo,
    active: s.active,
    sort_order: s.sort_order,
  }
}

/** 반복 지출 제안: 정기지출로 등록하지 않았는데 매달(매주) 나가는 지출을 등록하거나 아니라고 표시한다 */
export default function RecurringCandidates({ groups, onChanged }: { groups: RecurringGroup[]; onChanged: () => void }) {
  const { data, error, reload } = useLoad(() => recurringApi.recurringCandidates(), [])
  const [opened, setOpened] = useState<Opened | null>(null)
  const [linkPast, setLinkPast] = useState(true)
  const [showRejected, setShowRejected] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  if (error) return <p className="error">반복 지출 제안을 불러오지 못했어요: {error}</p>
  if (!data || (!data.pending.length && !data.rejected.length && !notice)) return null

  const act = async (run: () => Promise<unknown>) => {
    setActionError(null)
    try {
      await run()
      reload()
    } catch (e) {
      setActionError((e as Error).message)
    }
  }

  const open = (c: RecurringCandidate, merge: boolean) => {
    setNotice(null)
    setLinkPast(true)
    setOpened({ c, merge })
  }

  const accept = async (r: RecurringItemInput) => {
    const { c, merge } = opened!
    const res = await recurringApi.acceptCandidate(c.id, { item: r, item_id: merge ? c.similar_item!.id : undefined, link_past: linkPast })
    setNotice(`'${res.item.name}' ${merge ? '항목에 연결' : '항목을 만들고'} 결제 ${res.linked}건을 연결했어요. 다음 결제부터는 자동으로 확인돼요.`)
  }

  const today = todayISO()

  return (
    <article className="card cand-card">
      <h2>
        반복 지출 제안 {data.pending.length > 0 && <span className="chip upcoming">{data.pending.length}</span>}
      </h2>
      {data.pending.length > 0 && (
        <p className="muted small">정기지출로 등록하지 않았는데 가계부에서 반복해서 나가는 지출이에요. 등록하면 미확인 알림과 변동비 계산에 들어가요.</p>
      )}
      {notice && <p className="cand-notice small">✓ {notice}</p>}
      {actionError && <p className="error">{actionError}</p>}

      {data.pending.map((c) => (
        <div key={c.id} className="cand-row">
          <div className="cand-head">
            <span className="cand-name">{c.merchant}</span>
            <strong className="amt-fixed">{won(c.amount)}</strong>
          </div>
          <div className="muted small">
            {cadenceLabel(c)} · {c.occurrences}번 ({spanLabel(c)})
            {c.missing > 0 && ` · ${c.missing}번 빠짐`}
            {c.next_on >= today && ` · 다음 ${shortDate(c.next_on)} 예상`} · 신뢰도 {confidenceLabel(c.confidence)}
          </div>
          {c.similar_item && (
            <div className="small">
              금액이 비슷한 '{c.similar_item.name}'({won(c.similar_item.amount)})과 같은 지출일 수 있어요
              {c.similar_item.match_keyword ? '' : ' — 그 항목은 매칭 키워드가 비어 있어요'}
            </div>
          )}
          {c.warnings.map((w) => (
            <div key={w} className="cand-warn small">
              ⚠ {w}
            </div>
          ))}
          <div className="cand-actions">
            {c.similar_item && (
              <button className="primary" onClick={() => open(c, true)}>
                '{c.similar_item.name}'에 연결
              </button>
            )}
            <button className={c.similar_item ? '' : 'primary'} onClick={() => open(c, false)}>
              {c.similar_item ? '새 항목으로 등록' : '정기지출로 등록'}
            </button>
            <button onClick={() => act(() => recurringApi.rejectCandidate(c.id))} title="반복 지출이 아니라고 표시하면 다시 제안하지 않아요">
              아니에요
            </button>
          </div>
        </div>
      ))}

      {data.rejected.length > 0 && (
        <div className="cand-rejected">
          <button className="link small" onClick={() => setShowRejected((v) => !v)}>
            아니라고 한 제안 {data.rejected.length}건 {showRejected ? '접기' : '보기'}
          </button>
          {showRejected &&
            data.rejected.map((c) => (
              <div key={c.id} className="cand-head small">
                <span className="muted">
                  {c.merchant} · {cadenceLabel(c)} · {won(c.amount)}
                </span>
                <button className="link" onClick={() => act(() => recurringApi.restoreCandidate(c.id))}>
                  되돌리기
                </button>
              </div>
            ))}
        </div>
      )}

      {opened && (
        <RecurringForm
          key={`${opened.c.id}-${opened.merge}`}
          prefill={opened.merge ? mergedItem(opened.c) : opened.c.suggestion}
          title={opened.merge ? `'${opened.c.similar_item!.name}'에 연결` : '반복 지출을 정기지출로 등록'}
          groups={groups}
          submit={accept}
          onClose={() => setOpened(null)}
          onSaved={() => {
            setOpened(null)
            reload()
            onChanged()
          }}
        >
          {opened.merge && <MergeDiff c={opened.c} />}
          <label className="check">
            <input type="checkbox" checked={linkPast} onChange={(e) => setLinkPast(e.target.checked)} />
            지난 결제 {opened.c.occurrences}건도 이 정기지출로 연결
          </label>
          <span className="muted small">
            {linkPast
              ? '지난 기간들도 확인됨이 되고, 그 결제는 변동비에서 빠져요.'
              : '이번 기간 결제만 연결해요. 지난 기간 결제는 변동비로 남아요.'}
          </span>
        </RecurringForm>
      )}
    </article>
  )
}

/** 기존 항목에 합칠 때 무엇이 바뀌는지 */
function MergeDiff({ c }: { c: RecurringCandidate }) {
  const s = c.similar_item!
  const next = mergedItem(c)
  const changes = [
    s.match_keyword !== next.match_keyword && `키워드 '${s.match_keyword || '없음'}' → '${next.match_keyword}'`,
    s.amount !== next.amount && `금액 ${won(s.amount)} → ${won(next.amount)}`,
    s.day_of_month !== next.day_of_month && `출금일 ${dayLabel(s.day_of_month)} → ${dayLabel(next.day_of_month)}`,
  ].filter(Boolean)
  if (!changes.length) return null
  return <p className="muted small">실제 결제에 맞춰 바꿔요: {changes.join(' · ')}</p>
}
