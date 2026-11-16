import {
  closestCorners,
  DndContext,
  pointerWithin,
  type CollisionDetection,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { recurringApi, type RecurringGroup, type RecurringItem, type RecurringStatus, type RecurringStatusItem } from './api'
import { ledgerApi } from '../ledger/api'
import Bar from '../../shared/ui/Bar'
import PeriodNav from '../ledger/PeriodNav'
import GroupOrder from './GroupOrder'
import RecurringCandidates from './RecurringCandidates'
import RecurringForm from './RecurringForm'
import { parseISO, shortDate, todayISO, won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'

const STATUS_LABEL: Record<RecurringStatus, string> = {
  paid: '확인됨',
  upcoming: '예정',
  missed: '미확인',
  unset: '미설정',
  floating: '미정',
  skipped: '이번 달 스킵',
}

type Columns = Record<number, number[]> // group id → item ids (화면 순서)

const itemKey = (id: number) => `item-${id}`
const groupKey = (id: number) => `group-${id}`
const parseKey = (key: string) => Number(key.split('-')[1])

function buildColumns(groups: RecurringGroup[], items: RecurringItem[]): Columns {
  const cols: Columns = Object.fromEntries(groups.map((g) => [g.id, [] as number[]]))
  for (const item of items) (cols[item.group_id] ??= []).push(item.id) // 서버가 sort_order 순으로 준다
  return cols
}

/**
 * 놓을 곳은 포인터 위치로 정한다. 포인터 아래 항목이 있으면 그 항목, 카테고리 칸이면 그 칸(맨 끝).
 * 기본 closestCorners 는 끌고 있는 행 전체의 모서리로 판단해서, 칸의 마지막 자리에 놓으려 하면
 * 행 아래쪽이 다음 카테고리에 걸려 엉뚱한 칸으로 들어가는 문제가 있었다.
 */
const pointerFirst: CollisionDetection = (args) => {
  const hits = pointerWithin(args)
  if (hits.length) {
    const items = hits.filter((h) => String(h.id).startsWith('item-'))
    return items.length ? items : hits
  }
  return closestCorners(args) // 키보드 조작 등 포인터가 없을 때
}

function daysUntil(iso: string) {
  return Math.round((parseISO(iso).getTime() - parseISO(todayISO()).getTime()) / 86_400_000)
}

/** 항목 상태를 한 줄로 */
function statusLine(item: RecurringItem, st: RecurringStatusItem | undefined): { text: string; cls: string; title?: string } {
  const day = item.day_of_month ? `매월 ${item.day_of_month}일` : '출금일 미정'
  if (!item.active) return { text: `${day} · 사용 안 함`, cls: 'muted' }
  if (!st) return { text: day, cls: 'muted' }
  switch (st.status) {
    case 'paid':
      return { text: `${day} · ✓ ${shortDate(st.transaction!.occurred_on)}${st.early ? ' 미리' : ''} ${st.transaction!.merchant}`, cls: 'muted',
        title: st.early ? '수입일 전(지난 기간 날짜)에 미리 나간 결제를 이번 기간 몫으로 봤어요' : undefined }
    case 'missed':
      return { text: st.due_date ? `${day} · ${shortDate(st.due_date)} 지남` : `${day} · 이 기간에 나가지 않았어요`, cls: 'neg' }
    case 'floating':
      return { text: `${day} · 이번 기간 중 나가면 확인돼요`, cls: 'muted' }
    case 'skipped':
      return { text: `${day} · 이번 기간만 건너뜀 (다음 달에 다시 나타나요)`, cls: 'muted' }
    case 'upcoming': {
      if (!st.due_date) return { text: day, cls: 'muted' }
      const d = daysUntil(st.due_date)
      return { text: `${day} · ${shortDate(st.due_date)} 예정 (${d === 0 ? '오늘' : `D-${d}`})`, cls: 'muted' }
    }
    case 'unset':
      return { text: `${day} · 금액 입력 필요`, cls: 'muted' }
  }
}

export default function Recurring() {
  const [on, setOn] = useState<string>()
  const [editing, setEditing] = useState<RecurringItem | 'new' | null>(null)
  const { data: s, error, reload } = useLoad(() => ledgerApi.summary(on), [on])
  const { data: groups, reload: reloadGroups } = useLoad(() => recurringApi.recurringGroups(), [])
  // 사용 안 함 항목도 보여야 하므로 상태(summary)와 별도로 전체 목록을 불러온다
  const { data: allItems, reload: reloadItems } = useLoad(() => recurringApi.recurringItems(), [])

  // 놓은 직후 서버 응답 전까지 보여줄 순서
  const [dragColumns, setDragColumns] = useState<Columns | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [overGroup, setOverGroup] = useState<number | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [ordering, setOrdering] = useState(false)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  if (error) return <p className="error">{error}</p>

  const items = new Map((allItems ?? []).map((i) => [i.id, i]))
  const statusById = new Map<number, RecurringStatusItem>((s?.recurring.items ?? []).map((i) => [i.id, i]))
  const columns = dragColumns ?? (groups && allItems ? buildColumns(groups, allItems) : {})

  const findGroup = (key: string, cols: Columns): number | undefined => {
    if (key.startsWith('group-')) return parseKey(key)
    const id = parseKey(key)
    const found = Object.keys(cols).find((g) => cols[Number(g)].includes(id))
    return found === undefined ? undefined : Number(found)
  }

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(parseKey(String(e.active.id)))
    setSaveError(null)
  }

  // 다른 카테고리로 옮기는 건 놓는 순간에만 반영한다. 드래그 중에 항목을 옮기면 카드 높이가 바뀌어
  // 화면이 밀리고, 포인터가 이웃 카테고리에 걸려 왔다 갔다 하는 문제가 있었다. 대신 대상 카테고리를 강조한다.
  const onDragOver = ({ active, over }: DragOverEvent) => {
    const from = findGroup(String(active.id), columns)
    const to = over ? findGroup(String(over.id), columns) : undefined
    setOverGroup(to !== undefined && to !== from ? to : null)
  }

  const onDragEnd = async ({ active, over }: DragEndEvent) => {
    setActiveId(null)
    setOverGroup(null)
    if (!over || active.id === over.id) return
    const id = parseKey(String(active.id))
    const from = findGroup(String(active.id), columns)
    const to = findGroup(String(over.id), columns)
    if (from === undefined || to === undefined) return

    const overItem = String(over.id).startsWith('item-') ? parseKey(String(over.id)) : null
    let next: Columns
    if (from === to) {
      if (overItem === null) return
      const list = columns[from]
      next = { ...columns, [from]: arrayMove(list, list.indexOf(id), list.indexOf(overItem)) }
    } else {
      const target = columns[to]
      const at = overItem === null ? target.length : target.indexOf(overItem)
      next = { ...columns, [from]: columns[from].filter((x) => x !== id), [to]: [...target.slice(0, at), id, ...target.slice(at)] }
    }
    setDragColumns(next) // 서버 응답 전에 먼저 화면에 반영
    try {
      await recurringApi.reorderRecurring(Object.entries(next).map(([gid, ids]) => ({ group_id: Number(gid), item_ids: ids })))
      reloadItems()
      reload()
    } catch (e) {
      setSaveError((e as Error).message)
    }
    setDragColumns(null)
  }

  const done = () => {
    setEditing(null)
    reload()
    reloadItems()
    reloadGroups()
  }

  const dragging = activeId !== null

  return (
    <section className="page">
      <div className="page-header">
        <h1>정기지출</h1>
        <PeriodNav period={s?.period} onChange={setOn} />
      </div>

      {s && (
        <article className="card">
          <div className="stat-row">
            <div>
              <span className="muted">주수입</span>
              <strong className="pos">{won(s.income.planned)}</strong>
            </div>
            <div>
              <span className="muted">정기 · 저금</span>
              <strong className="amt-saving">{won(s.recurring.saving_total)}</strong>
            </div>
            <div>
              <span className="muted">정기 · 지출</span>
              <strong className="amt-fixed">{won(s.recurring.expense_total)}</strong>
            </div>
            <div>
              <span className="muted">변동비 할당 가능</span>
              <strong className={s.variable.pool < 0 ? 'neg' : 'amt-variable'}>{won(s.variable.pool)}</strong>
            </div>
          </div>
          {s.recurring.missed > 0 && <p className="neg small">확인되지 않은 정기지출 {s.recurring.missed}건</p>}
          {s.recurring.skipped_total > 0 && (
            <p className="muted small">이번 기간 스킵 {won(s.recurring.skipped_total)} — 정기지출 합계에서 빠지고 변동비 할당에 더해졌어요</p>
          )}
        </article>
      )}

      {groups && (
        <RecurringCandidates
          groups={groups}
          onChanged={() => {
            reload()
            reloadItems()
          }}
        />
      )}

      <div className="section-head">
        <span className="muted small">⠿ 끌어서 항목 순서·카테고리 변경 · 항목을 눌러 수정</span>
        <span className="toolbar">
          <button disabled={!groups?.length} onClick={() => setOrdering(true)}>
            ↕ 칸 순서
          </button>
          <button className="primary" disabled={!groups?.length} onClick={() => setEditing('new')}>
            ＋ 항목 추가
          </button>
        </span>
      </div>
      {ordering && groups && (
        <GroupOrder
          groups={groups}
          totals={
            new Map(groups.map((g) => [g.id, (allItems ?? []).filter((i) => i.group_id === g.id && i.active).reduce((a, i) => a + i.amount, 0)]))
          }
          onChanged={() => {
            reloadGroups()
            reloadItems()
          }}
          onDone={() => setOrdering(false)}
        />
      )}
      {saveError && <p className="error">순서 저장 실패: {saveError}</p>}

      <DndContext
        sensors={sensors}
        collisionDetection={pointerFirst}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setActiveId(null)
          setOverGroup(null)
        }}
      >
        {groups?.map((g) => {
          const ids = columns[g.id] ?? []
          // 빈 카테고리도 얇은 '놓을 자리'로 항상 보여준다 (드래그 시작 때 화면이 밀리지 않도록)
          const groupItems = ids.map((id) => items.get(id)).filter((x): x is RecurringItem => !!x)
          const active = groupItems.filter((i) => i.active && statusById.get(i.id)?.status !== 'skipped')
          const total = active.reduce((a, i) => a + i.amount, 0)
          const paid = active.reduce((a, i) => a + (statusById.get(i.id)?.status === 'paid' ? i.amount : 0), 0)
          return (
            <GroupCard
              key={g.id}
              group={g}
              total={total}
              paid={paid}
              empty={!ids.length}
              dragging={dragging}
              highlight={overGroup === g.id}
            >
              <SortableContext items={ids.map(itemKey)} strategy={verticalListSortingStrategy}>
                {groupItems.map((item) => (
                  <SortableRow
                    key={item.id}
                    item={item}
                    kind={g.kind}
                    status={statusById.get(item.id)}
                    onEdit={() => setEditing(item)}
                    onSkip={async (skip) => {
                      try {
                        if (skip) await recurringApi.skipRecurring(item.id, on)
                        else await recurringApi.unskipRecurring(item.id, on)
                      } catch (e) {
                        setSaveError((e as Error).message)
                      }
                      reload()
                    }}
                  />
                ))}
              </SortableContext>
            </GroupCard>
          )
        })}
      </DndContext>

      <p className="muted small">
        가계부에 매칭 키워드와 금액이 같은 거래가 들어오면 자동으로 확인 처리되고 변동비 집계에서 빠집니다. 정기지출 카테고리(저금·보험 등)는{' '}
        <Link to="/settings?tab=ledger">설정 &gt; 가계부설정</Link>에서 관리해요.
      </p>

      {editing && groups && (
        <RecurringForm
          initial={editing === 'new' ? undefined : editing}
          groups={groups}
          onClose={() => setEditing(null)}
          onSaved={done}
        />
      )}
    </section>
  )
}

function GroupCard({
  group,
  total,
  paid,
  empty,
  dragging,
  highlight,
  children,
}: {
  group: RecurringGroup
  total: number
  paid: number
  empty: boolean
  dragging: boolean
  highlight: boolean
  children: ReactNode
}) {
  const { setNodeRef } = useDroppable({ id: groupKey(group.id) })
  const tone = group.kind === 'saving' ? 'saving' : 'fixed'
  return (
    <article ref={setNodeRef} className={`card rgroup${empty ? ' empty' : ''}${highlight ? ' drop-over' : ''}`}>
      <header className="rgroup-head">
        <span className="rgroup-icon">{group.icon}</span>
        <span className="rgroup-name">{group.name}</span>
        <span className={`kind-tag ${group.kind}`}>{group.kind === 'saving' ? '저금' : '지출'}</span>
        <span className={`rgroup-total amt-${tone}`}>{won(total)}</span>
      </header>
      {total > 0 && (
        <div className="rgroup-progress">
          <Bar value={paid} max={total} kind="progress" tone={tone} />
          <span className="muted small">
            {won(paid)} 확인 · {won(total - paid)} 남음
          </span>
        </div>
      )}
      <div className="rlist">
        {children}
        {empty && (
          <div className={`drop-hint${dragging ? ' active' : ''}`}>
            {dragging ? `여기에 놓으면 '${group.name}'(으)로 옮겨져요` : '항목 없음'}
          </div>
        )}
      </div>
    </article>
  )
}

function SortableRow({
  item,
  kind,
  status,
  onEdit,
  onSkip,
}: {
  item: RecurringItem
  kind: 'saving' | 'expense'
  status: RecurringStatusItem | undefined
  onEdit: () => void
  onSkip: (skip: boolean) => void
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: itemKey(item.id),
  })
  const line = statusLine(item, status)
  const st = item.active ? status?.status : undefined
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`rrow${st ? ` ${st}` : ''}${item.active ? '' : ' inactive'}${isDragging ? ' dragging' : ''}`}
    >
      <button ref={setActivatorNodeRef} className="drag-handle" aria-label={`${item.name} 순서 바꾸기`} {...attributes} {...listeners}>
        ⠿
      </button>
      <button className="rrow-main" onClick={onEdit}>
        <span className="rrow-icon">{item.display_icon}</span>
        <span className="rrow-text">
          <span className="rrow-name">{item.name}</span>
          <span className={`rrow-sub ${line.cls}`} title={line.title ?? line.text}>
            {line.text}
          </span>
          {item.memo && (
            <span className="rrow-sub muted" title={item.memo}>
              {item.memo}
            </span>
          )}
        </span>
        <span className="rrow-right">
          <strong className={kind === 'saving' ? 'amt-saving' : 'amt-fixed'}>{won(item.amount)}</strong>
          {st ? <span className={`chip ${st}`}>{STATUS_LABEL[st]}</span> : !item.active && <span className="chip unset">꺼짐</span>}
        </span>
      </button>
      {/* 날짜가 지났는데 아직 안 나간 항목: 이번 기간만 건너뛰기 */}
      {st === 'missed' && (
        <button className="skip-button" onClick={() => onSkip(true)} title="이번 기간만 건너뛰고 다음 달에 다시 확인해요">
          스킵
        </button>
      )}
      {st === 'skipped' && (
        <button className="skip-button undo" onClick={() => onSkip(false)}>
          되돌리기
        </button>
      )}
    </div>
  )
}
