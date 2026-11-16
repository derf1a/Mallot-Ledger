/**
 * 절세 (올해 귀속연도) — 연말정산 공제 항목별 올해 예상액·공제·세금 감소·추가 여지와 결정세액 추정(stats.tax, 코드 계산).
 * 카드 사용은 결제 수단별 누적 막대 + 최저사용금액(총급여 25%) 눈금. 공제 항목은 한도 대비 연말 예상 막대.
 * 아래 '내 정보'(총급여·무주택 세대주·자녀 수)와 결제수단 분류를 고치면 저장 후 다시 계산한다(PUT /api/spending/tax-profile).
 */
import { useState, type ReactNode } from 'react'
import { won } from '../../shared/format'
import { StatTile } from '../../shared/charts'
import Bar from '../../shared/ui/Bar'
import { useTip } from '../../shared/ui/useTip'
import { insightsApi, type CardBucket, type PaymentKind, type SalaryParts, type TaxItem, type TaxProfile, type TaxStats } from './api'
import SalaryCalculator from './SalaryCalculator'

const BUCKETS: { key: CardBucket; label: string; rate: string; color: string }[] = [
  { key: 'credit', label: '신용카드', rate: '15%', color: 'var(--series-1)' },
  { key: 'debit', label: '체크·선불', rate: '30%', color: 'var(--series-3)' },
  { key: 'culture', label: '도서·공연·체육', rate: '30%', color: 'var(--series-5)' },
  { key: 'transit', label: '대중교통', rate: '40%', color: 'var(--series-4)' },
]
const KIND_LABEL: Record<PaymentKind, string> = { credit: '신용 15%', debit: '체크·선불 30%', none: '공제 안 됨' }
const STATUS: Record<TaxItem['status'], string | null> = { ok: null, check: '요건 확인', no: '요건 안 맞음', none: '해당 거래 없음' }

export default function TaxCard({ t, onSaved }: { t: TaxStats; onSaved: () => void }) {
  const s = t.summary
  return (
    <article className="card insights-wide tax-card">
      <h2>절세 <span className="muted small">{t.year}년 귀속 · 1월 1일~오늘 실제 + 연말까지 추정 · 세법 {t.rules_year}년 기준</span></h2>
      {t.notes.map((n) => <p key={n} className={`small ${t.gross_assumed && n.includes('총급여') ? 'alert warn' : 'muted'}`}>{n}</p>)}
      {s && (
        <div className="tile-row insights-tiles">
          <StatTile label="올해 예상 결정세액" value={`약 ${won(s.tax_now)}`} hint={`지방세 포함 · 한계세율 ${Math.round(s.marginal * 100)}%`} />
          <StatTile label="지금 공제로 줄어드는 세금" value={`약 ${won(s.saved)}`} hint={`공제가 없으면 약 ${won(s.tax_without)}`} />
          <StatTile label="연말까지 더 줄일 수 있는 세금" value={`약 ${won(s.extra_total)}`} hint="카드·연금계좌·청약을 한도까지 했을 때" />
        </div>
      )}
      {t.card && <CardUse t={t} />}
      {t.items.filter((x) => x.key !== 'card').length > 0 && (
        <ul className="tax-items">
          {t.items.filter((x) => x.key !== 'card').map((x) => <ItemRow key={x.key} x={x} />)}
        </ul>
      )}
      <Profile key={JSON.stringify(t.profile)} t={t} onSaved={onSaved} />
      <p className="muted small">
        추정이에요 — 4대보험·부양가족은 단순 가정이고, 실제 공제는 연말정산 간소화 자료와 회사 연말정산으로 확인하세요.
        {s?.special ? ' 주택자금·보험료 같은 특별공제가 표준세액공제(13만 원)보다 유리해 특별공제로 계산했어요.' : ''}
      </p>
    </article>
  )
}

function CardUse({ t }: { t: TaxStats }) {
  const c = t.card!
  const item = t.items.find((x) => x.key === 'card')
  const { box, show, showAt, hide, node } = useTip()
  const segs = BUCKETS.map((b) => ({ ...b, amount: c.projected[b.key] })).filter((b) => b.amount > 0)
  const whole = Math.max(c.total, c.threshold, 1)
  const tip = (b: (typeof segs)[number]): ReactNode => (
    <span className="viz-tip-row">
      <i className="viz-tip-key" style={{ background: b.color }} />
      <strong className="num">{won(b.amount)}</strong>
      <span className="muted">{b.label} · 공제율 {b.rate} · 올해 실제 {won(c.ytd[b.key])}</span>
    </span>
  )
  return (
    <section className="tax-cardsec">
      <div className="tax-row-head">
        <b>신용카드 등 사용액</b>
        <span className="muted small">올해 예상 {won(c.total)}</span>
        {item && item.effect > 0 && <span className="chip saving">세금 약 {won(item.effect)} 감소</span>}
      </div>
      <div className="home-alloc" ref={box} onMouseLeave={hide} role="group" aria-label="올해 카드 등 사용액 (연말까지 추정)">
        <div className="stack-bar tall tax-stack">
          {segs.map((b) => (
            <span key={b.key} tabIndex={0} className="stack-seg" aria-label={`${b.label} ${won(b.amount)}`}
              style={{ width: `${(b.amount / whole) * 100}%`, background: b.color }}
              onMouseMove={(e) => show(e, tip(b))} onFocus={(e) => showAt(e.currentTarget, tip(b))} onBlur={hide} />
          ))}
          <i className="tax-threshold" style={{ left: `${(c.threshold / whole) * 100}%` }} title={`최저사용금액 ${won(c.threshold)}`} />
        </div>
        {node}
      </div>
      <ul className="legend">
        {segs.map((b) => (
          <li key={b.key}><i style={{ background: b.color }} />{b.label} {b.rate} <span>{won(b.amount)}</span></li>
        ))}
        <li><i className="tax-threshold-key" />최저사용금액(총급여 25%) {won(c.threshold)}</li>
      </ul>
      <p className="small">
        {c.over > 0
          ? <>최저사용금액을 {won(c.over)} 넘어 소득공제 <b>{won(c.deduction)}</b> (계산액 {won(c.raw)}, 기본 한도 {won(c.limit)}).</>
          : <>최저사용금액까지 {won(-c.over)} 남아 아직 공제가 없어요 — 남은 기간은 공제율보다 카드 혜택을 보고 써도 돼요.</>}
        {item && item.extra_saving > 0 && <> 남은 기간 신용카드 몫 {won(item.room)}을 체크·선불로 쓰면 약 <b>{won(item.extra_saving)}</b> 더 줄어요.</>}
        {item && !item.extra_saving && c.over > 0 && c.raw >= c.limit && <> 이미 한도를 넘어 체크카드로 바꿔도 공제는 늘지 않아요.</>}
      </p>
      <p className="muted small">
        빠진 것: 계좌 출금 등 {won(c.projected.none)} · 보험·통신·공과금 등 {won(c.projected.excluded)}. 전통시장·해외 사용은 이름으로 가를 수 없어 위 분류에 섞여 있어요.
      </p>
    </section>
  )
}

function ItemRow({ x }: { x: TaxItem }) {
  const status = STATUS[x.status]
  const info = x.kind === 'info'
  return (
    <li className="tax-item">
      <div className="tax-row-head">
        <b>{x.title}</b>
        {status && <span className={`chip ${x.status === 'check' ? 'warn-chip' : 'muted-chip'}`}>{status}</span>}
        {x.sources.length > 0 && <span className="muted small">정기지출: {x.sources.join(', ')}</span>}
        {!info && x.effect > 0 && <span className="chip saving">세금 약 {won(x.effect)} 감소</span>}
      </div>
      {!info && (
        <div className="tax-meter">
          <Bar value={x.total} max={x.limit} kind="progress" tone="saving" />
          <span className="small num">
            연말 예상 {won(x.total)} <span className="muted">/ 한도 {won(x.limit)} · 올해 실제 {won(x.paid)}</span>
          </span>
        </div>
      )}
      <p className="small">
        {info
          ? <>올해 납입 {won(x.paid)} · 비과세 한도 {won(x.deduction)}. 만기 자금을 연금계좌로 옮기면 공제 한도가 최대 {won(x.room)} 늘어 최대 약 {won(x.extra_saving)} 더 돌려받아요(만기 때).</>
          : <>{x.kind === 'income_deduction' ? '소득공제' : '세액공제 대상'} {won(x.deduction)}.
            {x.extra_saving > 0 && <> 연말까지 <b>{won(x.useful)}</b> 더 내면 약 <b>{won(x.extra_saving)}</b> 더 줄어요
              {x.useful < x.room - 10_000 ? ` (한도는 ${won(x.room)} 남았지만 그 이상은 낼 세금이 없어요)` : ''}.</>}</>}
      </p>
      <details className="tax-req">
        <summary className="muted small">요건 · {x.law}</summary>
        <p className="muted small">{x.requirement}</p>
      </details>
    </li>
  )
}

function Profile({ t, onSaved }: { t: TaxStats; onSaved: () => void }) {
  const [p, setP] = useState<TaxProfile>(() => ({ ...t.profile, payment_kinds: { ...t.profile.payment_kinds } }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [calc, setCalc] = useState(false)
  const kindOf = (m: TaxStats['methods'][number]) => p.payment_kinds[m.method] ?? m.kind
  const guessed = t.methods.filter((m) => m.guessed && !(m.method in p.payment_kinds)).length
  const save = async (body: TaxProfile = p) => {
    setBusy(true)
    setError(null)
    try {
      await insightsApi.saveTaxProfile(body)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="tax-profile" open={t.gross_assumed || !t.available}>
      <summary><b>내 정보</b> <span className="muted small">총급여·무주택 세대주·자녀 수 · 결제수단 분류{guessed ? ` (추정 ${guessed}개)` : ''}</span></summary>
      <div className="tax-profile-form">
        <label>
          연 총급여 (세전, 비과세 뺀 것)
          <input type="number" inputMode="numeric" min={0} value={p.gross_salary || ''} placeholder={`비우면 월 주수입 × 12`}
            onChange={(e) => setP({ ...p, gross_salary: Number(e.target.value) })} />
          {p.gross_salary > 0 && <span className="muted small">{won(p.gross_salary)}</span>}
          <button type="button" className="link small tax-calc-open" onClick={() => setCalc((v) => !v)}>{calc ? '계산기 닫기' : '계산기로 구하기'}</button>
        </label>
        <label>
          무주택 세대주
          <select value={p.homeless_head === null ? '' : p.homeless_head ? 'yes' : 'no'}
            onChange={(e) => setP({ ...p, homeless_head: e.target.value === '' ? null : e.target.value === 'yes' })}>
            <option value="">모름 (예로 계산)</option>
            <option value="yes">예</option>
            <option value="no">아니요</option>
          </select>
        </label>
        <label>
          자녀 수 <span className="muted small">카드 공제 한도에만 반영</span>
          <input type="number" inputMode="numeric" min={0} max={20} value={p.children}
            onChange={(e) => setP({ ...p, children: Math.max(0, Number(e.target.value) || 0) })} />
        </label>
      </div>
      {calc && (
        <SalaryCalculator value={p.salary_parts} children_={p.children} busy={busy} onUse={(parts: SalaryParts, gross: number) => {
          const next = { ...p, gross_salary: gross, salary_parts: parts }
          setP(next)
          setCalc(false)
          void save(next)
        }} />
      )}
      {t.methods.length > 0 && (
        <details className="tax-methods-box" open={guessed > 0 && !t.gross_assumed}>
          <summary className="small">결제수단 분류 {t.methods.length}개{guessed ? ` · 이름으로 추정 ${guessed}개 — 맞는지 골라 주세요` : ''}</summary>
          <p className="muted small">체크·선불 = 체크카드·직불·페이 머니 같은 선불전자지급수단·현금영수증. 간편결제는 연결한 카드에 따라 달라요. 계좌 출금은 현금영수증을 받았을 때만 공제돼요.</p>
          <table className="data-table small tax-methods">
            <thead><tr><th scope="col">결제수단</th><th scope="col">올해 사용</th><th scope="col">공제 분류</th></tr></thead>
            <tbody>
              {t.methods.map((m) => (
                <tr key={m.method}>
                  <th scope="row">{m.method || <span className="muted">(결제수단 없음)</span>}</th>
                  <td className="num" title={`${m.count}건`}>{won(m.ytd)}</td>
                  <td>
                    <select value={kindOf(m)} aria-label={`${m.method || '결제수단 없음'} 공제 분류`}
                      onChange={(e) => setP({ ...p, payment_kinds: { ...p.payment_kinds, [m.method]: e.target.value as PaymentKind } })}>
                      {(Object.keys(KIND_LABEL) as PaymentKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
                    </select>
                    {m.guessed && !(m.method in p.payment_kinds) && <span className="chip warn-chip" title="이름으로 추정했어요 — 맞는지 골라 주세요">추정</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <div className="tax-profile-actions">
        <button className="primary" disabled={busy} onClick={() => save()}>{busy ? '계산 중…' : '저장하고 다시 계산'}</button>
        {error && <span className="error small">{error}</span>}
      </div>
    </details>
  )
}
