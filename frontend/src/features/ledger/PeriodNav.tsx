import { useRef } from 'react'
import type { Period } from './api'
import { addDays, parseISO } from '../../shared/format'

interface Props {
  period: Period | undefined
  onChange: (on: string) => void
}

const label = (p: Period) => {
  const s = parseISO(p.start)
  const e = parseISO(p.end)
  const year = s.getFullYear() !== new Date().getFullYear() ? `${s.getFullYear()}년 ` : ''
  return `${year}${s.getMonth() + 1}.${s.getDate()} ~ ${e.getMonth() + 1}.${e.getDate()}`
}

/** 수입일 기준 한 달 단위로 이동. 가운데 라벨을 누르면 월을 골라 바로 이동한다 (그 달 수입일에 시작하는 기간) */
export default function PeriodNav({ period, onChange }: Props) {
  const monthRef = useRef<HTMLInputElement>(null)
  const start = period ? parseISO(period.start) : null
  const monthValue = start ? `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}` : ''
  return (
    <div className="period-nav">
      <button aria-label="이전 기간" disabled={!period} onClick={() => period && onChange(addDays(period.start, -1))}>
        ‹
      </button>
      <button
        className="period-label"
        disabled={!period}
        title="월 선택"
        onClick={() => monthRef.current?.showPicker?.() ?? monthRef.current?.focus()}
      >
        {period ? label(period) : '…'}
        <input
          ref={monthRef}
          type="month"
          className="period-month-input"
          value={monthValue}
          aria-label="월 선택"
          onChange={(e) => {
            if (!e.target.value || !start) return
            // 고른 달의 '수입일' 날짜가 속한 기간으로 — 현재 기간의 시작일(=수입일)과 같은 일(day)을 쓴다
            const [y, m] = e.target.value.split('-').map(Number)
            const last = new Date(y, m, 0).getDate()
            onChange(`${y}-${String(m).padStart(2, '0')}-${String(Math.min(start.getDate(), last)).padStart(2, '0')}`)
          }}
        />
      </button>
      <button aria-label="다음 기간" disabled={!period} onClick={() => period && onChange(addDays(period.end, 1))}>
        ›
      </button>
    </div>
  )
}
