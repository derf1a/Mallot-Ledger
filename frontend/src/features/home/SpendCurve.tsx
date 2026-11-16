/**
 * 이번 기간 변동비 누적 — 이번 기간(변동비 색 선) · 지난 기간(회색 선) · 예산 속도(가는 기준선), 축은 하나.
 * 마우스를 올리면(터치는 누르고 끌기, 키보드는 ←→) 세로선이 가장 가까운 날짜에 붙고, 그날까지 누적·지난 기간 같은 날·
 * 예산 속도·그날 쓴 돈과 큰 결제를 한 설명에 보여 준다. 누르면(터치는 같은 날을 한 번 더) 가계부에서 그날 거래를 연다.
 */
import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { HomeTrend } from './api'
import { longDate, shortDate, won } from '../../shared/format'
import { compact } from '../insights/format'
import { niceTicks, useWidth } from '../../shared/chartUtils'

const H = 200
const M = { top: 16, right: 14, bottom: 22, left: 46 }

const running = (xs: number[]) => {
  let sum = 0
  return xs.map((x) => (sum += x))
}

export default function SpendCurve({ trend, budget }: { trend: HomeTrend; budget: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const navigate = useNavigate()
  const [at, setAt] = useState<number | null>(null)
  const pointer = useRef('mouse') // 마지막으로 누른 입력 — 마우스는 바로 열고 터치는 두 번

  const days = trend.daily
  const n = days.length
  // 지난 기간이면 끝까지, 아직 오지 않은 기간이면 그릴 것이 없다
  const last = trend.today > trend.period.end ? n - 1 : days.findIndex((d) => d.date === trend.today)
  const cur = running(days.map((d) => d.spent)).slice(0, last + 1)
  const prev = running(trend.previous.daily).slice(0, n)
  const pace = (i: number) => (budget * (i + 1)) / n

  const lo = Math.min(0, ...cur, ...prev)
  const ticks = niceTicks(lo, Math.max(...cur, ...prev, budget, 1), 3)
  const hi = Math.max(...cur, ...prev, budget, ticks[ticks.length - 1] ?? 1)
  const plotW = Math.max(width - M.left - M.right, 1)
  const x = (i: number) => M.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2)
  const y = (v: number) => M.top + (1 - (v - lo) / (hi - lo || 1)) * (H - M.top - M.bottom)
  const line = (vs: number[]) => vs.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')

  const indexAt = (clientX: number, el: Element) => {
    const r = el.getBoundingClientRect()
    return Math.round(Math.min(Math.max((clientX - r.left - M.left) / plotW, 0), 1) * (n - 1))
  }
  const open = (i: number) => navigate(`/ledger?day=${days[i].date}`)
  const onDown = (e: PointerEvent<SVGRectElement>) => {
    pointer.current = e.pointerType
    if (e.pointerType === 'mouse') return
    const i = indexAt(e.clientX, e.currentTarget)
    if (i === at) open(i) // 터치: 설명이 떠 있는 날을 한 번 더 누르면 연다
    else setAt(i)
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      setAt((i) => Math.min(Math.max((i ?? Math.max(last, 0)) + (e.key === 'ArrowLeft' ? -1 : 1), 0), n - 1))
    } else if (e.key === 'Enter' && at !== null) open(at)
  }

  const end = cur.length - 1
  const d = at !== null ? days[at] : null
  const tipLeft = at !== null && x(at) < width / 2
  const spentToday = cur[end] ?? 0
  const summary = `${trend.period.start}부터 ${end + 1}일 동안 변동비 ${won(spentToday)}` +
    (prev[end] !== undefined ? `, 지난 기간 같은 날 ${won(prev[end])}` : '')

  return (
    <div className="curve" ref={ref} tabIndex={0} role="group" aria-label={`변동비 누적 그림. ${summary}. 좌우 화살표로 날짜를 고르고 Enter 로 그날 거래 보기`}
      onKeyDown={onKey} onFocus={() => setAt((i) => i ?? Math.max(last, 0))} onBlur={() => setAt(null)}>
      {width > 0 && (
        <svg width={width} height={H} aria-hidden>
          {ticks.map((t) => (
            <g key={t}>
              <line className="curve-grid" x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
              <text className="curve-tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{compact(t)}</text>
            </g>
          ))}
          <text className="curve-tick" x={x(0)} y={H - 6} textAnchor="start">{shortDate(days[0].date)}</text>
          <text className="curve-tick" x={x(n - 1)} y={H - 6} textAnchor="end">{shortDate(days[n - 1].date)}</text>
          {budget > 0 && (
            <>
              <line className="curve-pace" x1={x(0)} y1={y(0)} x2={x(n - 1)} y2={y(budget)} />
              <text className="curve-tick" x={x(n - 1)} y={y(budget) - 7} textAnchor="end">예산 {compact(budget)}</text>
            </>
          )}
          {prev.length > 1 && <path className="curve-prev" d={line(prev)} />}
          {cur.length > 1 && (
            <>
              <path className="curve-area" d={`${line(cur)}L${x(end)},${y(Math.max(lo, 0))}L${x(0)},${y(Math.max(lo, 0))}Z`} />
              <path className="curve-cur" d={line(cur)} />
            </>
          )}
          {end >= 0 && at === null && (
            <>
              <circle className="curve-dot" cx={x(end)} cy={y(spentToday)} r={4.5} />
              <text className="curve-end" x={x(end) + (x(end) > width - 90 ? -10 : 10)} y={y(spentToday) - 10}
                textAnchor={x(end) > width - 90 ? 'end' : 'start'}>{compact(spentToday)}</text>
            </>
          )}
          {at !== null && (
            <g>
              <line className="curve-cross" x1={x(at)} x2={x(at)} y1={M.top - 6} y2={H - M.bottom} />
              {at < prev.length && <circle className="curve-dot prev" cx={x(at)} cy={y(prev[at])} r={4} />}
              {at <= end && <circle className="curve-dot" cx={x(at)} cy={y(cur[at])} r={4.5} />}
            </g>
          )}
          <rect className="curve-hit" x={M.left - 8} y={0} width={plotW + 16} height={H - M.bottom}
            onPointerMove={(e) => e.pointerType === 'mouse' && setAt(indexAt(e.clientX, e.currentTarget))}
            onPointerLeave={(e) => e.pointerType === 'mouse' && setAt(null)}
            onPointerDown={onDown}
            onClick={() => at !== null && pointer.current === 'mouse' && open(at)} />
        </svg>
      )}
      {d && at !== null && (
        <div className="home-tip" role="status" style={tipLeft ? { left: x(at) + 14 } : { right: width - x(at) + 14 }}>
          <div className="home-tip-head">
            <b>{longDate(d.date)}</b>
            <span className="muted">{at + 1}일째</span>
          </div>
          {at <= end && <TipRow color="var(--c-variable)" value={won(cur[at])} label="이번 기간 누적" />}
          {at < prev.length && <TipRow color="var(--series-other)" value={won(prev[at])} label="지난 기간 같은 날" />}
          {budget > 0 && <TipRow value={won(Math.round(pace(at)))} label="예산 속도" />}
          {at <= end && at < prev.length && (
            <span className="muted">
              지난 기간보다 {won(Math.abs(cur[at] - prev[at]))} {cur[at] > prev[at] ? '더' : '덜'} 썼어요
            </span>
          )}
          {at <= end && (
            <div className="home-tip-sub">
              <span>
                이날 <b>{won(d.spent)}</b> {d.count > 0 && <span className="muted">· {d.count}건</span>}
              </span>
              {d.top.map((t, i) => (
                <span key={i} className="home-tip-line">
                  <span className="home-tip-name">{t.icon} {t.merchant || '(이름 없음)'}</span>
                  <span className="num">{won(t.amount)}</span>
                </span>
              ))}
              {d.count > 0 && <span className="muted small">누르면 그날 거래 보기</span>}
            </div>
          )}
        </div>
      )}
      <ul className="legend-line curve-legend">
        <li><i className="viz-tip-key" style={{ background: 'var(--c-variable)' }} />이번 기간</li>
        <li><i className="viz-tip-key" style={{ background: 'var(--series-other)' }} />지난 기간 ({shortDate(trend.previous.start)} ~ {shortDate(trend.previous.end)})</li>
        {budget > 0 && <li><i className="viz-tip-key pace" />예산 속도</li>}
      </ul>
    </div>
  )
}

function TipRow({ value, label, color }: { value: string; label: string; color?: string }) {
  return (
    <span className="viz-tip-row">
      <i className={`viz-tip-key${color ? '' : ' pace'}`} style={color ? { background: color } : undefined} />
      <strong className="num">{value}</strong>
      <span className="muted">{label}</span>
    </span>
  )
}
