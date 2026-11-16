/**
 * 소비 습관 그림 — 세로 막대(기간별 카테고리 누적 · 요일 · 시간대)와 많이 쓴 곳 목록.
 * 색은 정체성(카테고리)에만 쓰고 글자는 글자색. 칸에 마우스를 올리거나 포커스하면 그 칸의 값을 모두 보여 준다(값이 먼저).
 * 막대는 24px 이하, 위쪽만 둥글게, 누적 조각 사이 2px 틈. 표로 보기는 화면(Insights)이 붙인다.
 */
import type { ReactNode } from 'react'
import { useTip } from '../../shared/ui/useTip'
import { niceTicks } from '../../shared/chartUtils'
import { won } from '../../shared/format'
import { compact } from './format'

export interface Seg {
  key: string
  name: string
  value: number
  color: string
}

export interface Col {
  key: string
  label: string
  segs: Seg[]
  tip: ReactNode
}

interface Band {
  start: number // 칸 번호 (포함)
  end: number
  label: string
}

/** 세로 막대 (누적 가능). labelEvery: x 라벨 간격, bands: 뒤에 까는 구간 표시(분석 기간·밤) */
export function Columns({ cols, height = 170, labelEvery = 1, bands = [], ariaLabel }: {
  cols: Col[]
  height?: number
  labelEvery?: number
  bands?: Band[]
  ariaLabel: string
}) {
  const { box, show, showAt, hide, node } = useTip()
  const totals = cols.map((c) => c.segs.reduce((a, s) => a + Math.max(0, s.value), 0))
  const top = Math.max(...totals, 1)
  const ticks = niceTicks(0, top, 3)
  const max = Math.max(top, ticks[ticks.length - 1] ?? top)
  const peak = totals.indexOf(Math.max(...totals))
  const pctOf = (i: number) => `${(i / cols.length) * 100}%`
  return (
    <div className="cols" ref={box} onMouseLeave={hide} role="group" aria-label={ariaLabel}>
      <div className="cols-plot" style={{ height }}>
        {ticks.map((t) => (
          <div key={t} className="cols-grid" style={{ bottom: `${(t / max) * 100}%` }}>
            <span>{compact(t)}</span>
          </div>
        ))}
        <div className="cols-area">
          {bands.map((b) => (
            <div key={`${b.start}-${b.label}`} className="cols-band" style={{ left: pctOf(b.start), width: pctOf(b.end - b.start + 1) }}>
              <span>{b.label}</span>
            </div>
          ))}
          {cols.map((c, i) => (
            <div key={c.key} className="col-slot" tabIndex={0} aria-label={`${c.label} ${won(totals[i])}`}
              onMouseMove={(e) => show(e, c.tip)} onFocus={(e) => showAt(e.currentTarget, c.tip)} onBlur={hide}>
              {i === peak && totals[i] > 0 && <span className="col-cap" style={{ bottom: `${(totals[i] / max) * 100}%` }}>{compact(totals[i])}</span>}
              <div className="col" style={{ height: `${(totals[i] / max) * 100}%` }}>
                {c.segs.filter((s) => s.value > 0).map((s) => (
                  <i key={s.key} style={{ flexGrow: s.value, background: s.color }} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="cols-x" aria-hidden>
        {cols.map((c, i) => <span key={c.key}>{i % labelEvery === 0 ? c.label : ''}</span>)}
      </div>
      {node}
    </div>
  )
}

/** 툴팁 본문 — 값이 먼저, 이름은 뒤 (선 표시로 계열 구분) */
export function TipRows({ title, rows, foot }: { title: string; rows: { name: string; value: number; color?: string }[]; foot?: ReactNode }) {
  return (
    <>
      <span className="muted">{title}</span>
      {rows.map((r) => (
        <span key={r.name} className="viz-tip-row">
          {r.color && <i className="viz-tip-key" style={{ background: r.color }} />}
          <b>{won(r.value)}</b> {r.name}
        </span>
      ))}
      {foot && <span className="muted">{foot}</span>}
    </>
  )
}

/** 많이 쓴 곳 — 가로 막대(단일 계열이라 범례 없음), 값은 막대 옆 글자색으로 */
export function MerchantBars({ items }: { items: { name: string; count: number; sum: number; avg: number; category: string }[] }) {
  const max = Math.max(...items.map((m) => m.sum), 1)
  return (
    <ul className="merchant-bars">
      {items.map((m) => (
        <li key={m.name}>
          <span className="merchant-name">
            <b>{m.name}</b>
            <span className="muted small">{m.category} · {m.count}건 · 1회 {won(m.avg)}</span>
          </span>
          <span className="merchant-track" aria-hidden><i style={{ width: `${(m.sum / max) * 100}%` }} /></span>
          <span className="num merchant-sum">{won(m.sum)}</span>
        </li>
      ))}
    </ul>
  )
}
