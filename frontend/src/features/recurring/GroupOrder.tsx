import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState } from 'react'
import { recurringApi, type RecurringGroup } from './api'
import { won } from '../../shared/format'

interface Props {
  groups: RecurringGroup[]
  totals: Map<number, number>
  onChanged: () => void
  onDone: () => void
}

/** 정기지출 카테고리(칸) 순서 바꾸기: 칸을 한 줄로 접어 보여주고 ⠿ 로 끌어 놓으면 바로 저장 */
export default function GroupOrder({ groups, totals, onChanged, onDone }: Props) {
  const [order, setOrder] = useState(groups.map((g) => g.id))
  const [error, setError] = useState<string | null>(null)
  const byId = new Map(groups.map((g) => [g.id, g]))
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const onDragEnd = async ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const next = arrayMove(order, order.indexOf(Number(active.id)), order.indexOf(Number(over.id)))
    setOrder(next)
    try {
      await recurringApi.reorderRecurringGroups(next)
      setError(null)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
      setOrder(order)
    }
  }

  return (
    <article className="card group-order">
      <div className="section-head">
        <h2>칸 순서 바꾸기</h2>
        <button className="primary" onClick={onDone}>
          완료
        </button>
      </div>
      <p className="muted small">⠿ 를 잡고 끌어서 정기지출 카테고리 칸의 순서를 바꿔요. 놓는 즉시 저장돼요.</p>
      {error && <p className="error small">{error}</p>}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={order} strategy={verticalListSortingStrategy}>
          {order.map((id) => {
            const g = byId.get(id)
            return g ? <GroupRow key={id} group={g} total={totals.get(id) ?? 0} /> : null
          })}
        </SortableContext>
      </DndContext>
    </article>
  )
}

function GroupRow({ group, total }: { group: RecurringGroup; total: number }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: group.id })
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={`group-order-row${isDragging ? ' dragging' : ''}`}>
      <button ref={setActivatorNodeRef} className="drag-handle" aria-label={`${group.name} 칸 순서 바꾸기`} {...attributes} {...listeners}>
        ⠿
      </button>
      <span className="rgroup-icon">{group.icon}</span>
      <span className="rgroup-name">{group.name}</span>
      <span className={`kind-tag ${group.kind}`}>{group.kind === 'saving' ? '저금' : '지출'}</span>
      <span className={`rgroup-total ${group.kind === 'saving' ? 'amt-saving' : 'amt-fixed'}`}>
        {won(total)} <span className="muted small">· {group.item_count ?? 0}개</span>
      </span>
    </div>
  )
}
