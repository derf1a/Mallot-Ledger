/** 홈 화면 계산 (컴포넌트가 아닌 것 — Fast Refresh) */
import type { Period } from '../ledger/api'
import type { RecurringStatus } from '../recurring/api'
import { parseISO } from '../../shared/format'

export const STATUS_LABEL: Record<RecurringStatus, string> = {
  paid: '냈어요',
  upcoming: '예정',
  missed: '미확인',
  unset: '금액 미설정',
  floating: '날짜 미정',
  skipped: '이번엔 건너뜀',
}

const DAY = 86_400_000

export const daysBetween = (a: string, b: string) => Math.round((parseISO(b).getTime() - parseISO(a).getTime()) / DAY)

/** 기간 안에서 오늘의 위치: 지난 날 수(오늘 포함)·남은 날 수(오늘 포함)·지난 비율. 지난 기간이면 끝, 앞으로 올 기간이면 0 */
export function progress(p: Period, today: string) {
  const length = daysBetween(p.start, p.end) + 1
  const elapsed = today < p.start ? 0 : today > p.end ? length : daysBetween(p.start, today) + 1
  return { length, elapsed, left: length - elapsed + (today >= p.start && today <= p.end ? 1 : 0), ratio: elapsed / length,
    current: today >= p.start && today <= p.end }
}

/** 바뀐 비율 (+12%) — 비교 대상이 없으면 null */
export const changeText = (now: number, before: number) =>
  before > 0 ? `${now >= before ? '+' : '−'}${Math.abs(Math.round(((now - before) / before) * 100))}%` : null
