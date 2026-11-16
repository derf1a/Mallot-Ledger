/** 설정의 가계부 탭들 — 개인설정(이름 · 월 주수입 · 수입일 · 내 계좌) · 가계부(카테고리 · 정기지출 칸 · 가맹점 규칙) · 데이터(뱅크샐러드 가져오기 · 판독 기록 · DB 백업). Mallot 에서 옮김 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { budgetApi, type Category } from '../budget/api'
import { ledgerApi, type Account, type ImportReport, type MerchantRule, type Settings as SettingsT } from '../ledger/api'
import { recurringApi, type RecurringGroup, type RecurringKind } from '../recurring/api'
import { systemApi } from './api'
import IconPicker from '../../shared/ui/IconPicker'
import { useLoad } from '../../shared/useLoad'
import { useReadOnly } from '../../shared/readOnly'

function useSaver() {
  const [message, setMessage] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>, ok = '저장했어요') => {
    try {
      await fn()
      setMessage(ok)
    } catch (e) {
      setMessage((e as Error).message)
    }
    setTimeout(() => setMessage(null), 2500)
  }
  return { message, run }
}

export function PersonalSettings() {
  const { data: settings } = useLoad(() => ledgerApi.settings(), [])
  const { data: accounts, reload } = useLoad(() => ledgerApi.accounts(), [])
  return (
    <>
      {settings && <ProfileForm initial={settings} />}
      <article className="card">
        <h2>내 계좌</h2>
        <p className="muted small">
          여기 등록한 계좌로 보내는 이체는 <b>내 계좌 간 이체(±0)</b>로 처리돼요. 키워드는 거래내역의 받는 사람에 나오는 글자(예: 토스뱅크, 계좌 끝자리)를 쉼표로 구분해 적어요.
        </p>
        {accounts?.map((a) => (
          <AccountRow key={a.id} account={a} onChange={reload} />
        ))}
        <AccountRow onChange={reload} />
      </article>
    </>
  )
}

function ProfileForm({ initial }: { initial: SettingsT }) {
  const [s, setS] = useState(initial)
  const { message, run } = useSaver()
  return (
    <article className="card">
      <h2>개인설정</h2>
      <div className="form">
        <label>
          이름
          <input value={s.owner_name} onChange={(e) => setS({ ...s, owner_name: e.target.value })} />
        </label>
        <label>
          월 주수입 (원)
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={s.monthly_income || ''}
            onChange={(e) => setS({ ...s, monthly_income: Number(e.target.value) })}
          />
        </label>
        <label>
          수입일 (가계부 한 달의 시작일 — 예: 21이면 21일 ~ 다음 달 20일)
          <select value={s.payday} onChange={(e) => setS({ ...s, payday: Number(e.target.value) })}>
            {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>
                매월 {d}일{d > 28 ? ' (없는 달은 말일)' : ''}
              </option>
            ))}
          </select>
        </label>
        <label>
          가계부 검색 기본 범위
          <select value={s.search_months} onChange={(e) => setS({ ...s, search_months: Number(e.target.value) })}>
            {[3, 6, 12, 24, 36].map((m) => (
              <option key={m} value={m}>
                최근 {m % 12 === 0 ? `${m / 12}년` : `${m}개월`}
              </option>
            ))}
            <option value={0}>전체 기간</option>
          </select>
          <span className="muted small">검색하거나 필터를 걸면 한 달이 아니라 이 범위에서 찾아요 (검색 화면에서 바로 바꿀 수도 있어요).</span>
        </label>
        <label>
          빌린 돈을 받는 상대 (쉼표 구분)
          <input
            placeholder="예: 부모님 이름"
            value={s.loan_counterparties}
            onChange={(e) => setS({ ...s, loan_counterparties: e.target.value })}
          />
          <span className="muted small">이 상대에게서 받은 입금은 수입이 아니라 빌린 돈(±0)으로 처리해요. 갚는 출금은 정기지출(예: 부모님 상환)로 매칭돼요.</span>
        </label>
        <div className="form-actions">
          {message && <span className="muted small">{message}</span>}
          <button className="primary" onClick={() => run(() => ledgerApi.saveSettings(s))}>
            저장
          </button>
        </div>
      </div>
    </article>
  )
}

function AccountRow({ account, onChange }: { account?: Account; onChange: () => void }) {
  const [a, setA] = useState({ name: account?.name ?? '', keyword: account?.keyword ?? '' })
  const { message, run } = useSaver()
  const save = () =>
    run(async () => {
      if (account) await ledgerApi.updateAccount(account.id, a)
      else {
        await ledgerApi.createAccount(a)
        setA({ name: '', keyword: '' })
      }
      onChange()
    })
  return (
    <div className="edit-row">
      <input placeholder="계좌 이름 (예: 토스 비상금)" value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} />
      <input placeholder="매칭 키워드 (예: 토스뱅크,1234)" value={a.keyword} onChange={(e) => setA({ ...a, keyword: e.target.value })} />
      <button disabled={!a.name} onClick={save}>
        {account ? '저장' : '추가'}
      </button>
      {account && (
        <button className="danger-text" onClick={() => run(async () => { await ledgerApi.deleteAccount(account.id); onChange() }, '삭제했어요')}>
          삭제
        </button>
      )}
      {message && <span className="muted small">{message}</span>}
    </div>
  )
}

export function LedgerSettings() {
  const { data: categories } = useLoad(() => budgetApi.categories(), [])
  const { data: groups, reload: reloadGroups } = useLoad(() => recurringApi.recurringGroups(), [])

  return (
    <>
      <article className="card">
        <h2>변동비 카테고리 · 월 예산</h2>
        <p className="muted small">
          카테고리 추가·수정·삭제와 예산 배정은 <Link to="/ledger/budget">가계부 &gt; Budget(변동비 관리)</Link>으로 옮겼어요. 지난 기간·최근 평균
          사용액을 보면서 할당 가능액을 나눠 줄 수 있어요.
        </p>
      </article>

      <article className="card">
        <h2>정기지출 카테고리</h2>
        <p className="muted small">
          정기지출 항목을 묶는 분류예요. <b className="amt-saving">저금</b>은 예·적금·투자처럼 쌓이는 돈, <b className="amt-fixed">지출</b>은
          보험·구독처럼 나가는 돈으로 색을 다르게 보여줘요. 항목 자체는 <Link to="/ledger/recurring">정기지출</Link> 화면에서 추가·수정해요.
        </p>
        {groups?.map((g) => (
          <GroupRow key={g.id} group={g} onChange={reloadGroups} />
        ))}
        <GroupRow onChange={reloadGroups} />
      </article>

      {categories && <MerchantRules categories={categories} />}
    </>
  )
}

/** 가맹점 분류 규칙 (#2): 카테고리를 직접 고르면 쌓이고, 같은 가맹점에 자동 적용된다 */
function MerchantRules({ categories }: { categories: Category[] }) {
  const [q, setQ] = useState('')
  const { data: rules, reload } = useLoad(() => ledgerApi.merchantRules(q), [q])
  const { message, run } = useSaver()
  return (
    <article className="card">
      <h2>가맹점 분류 규칙</h2>
      <p className="muted small">
        거래의 카테고리를 직접 고르면 가맹점별로 기억했다가, 같은 가맹점(지점이 달라도)이 다시 들어오면 자동으로 분류해요. 캡쳐 판독에서도 AI보다 내
        규칙이 우선이에요. <b>직접</b>은 내가 고른 규칙, <b>AI</b>는 AI 분류를 그대로 저장해서 생긴 약한 규칙이에요.
      </p>
      <input className="search" placeholder="가맹점 검색" value={q} onChange={(e) => setQ(e.target.value)} />
      {rules?.length === 0 && <p className="muted small">{q ? '검색 결과가 없어요.' : '아직 규칙이 없어요. 거래의 카테고리를 직접 고르면 생겨요.'}</p>}
      {rules?.map((r: MerchantRule) => (
        <div key={r.id} className="edit-row">
          <span className="w-name rule-key">{r.merchant_key}</span>
          <select
            value={r.category_id}
            aria-label={`${r.merchant_key} 카테고리`}
            onChange={(e) =>
              run(async () => {
                await ledgerApi.updateRule(r.id, Number(e.target.value))
                reload()
              })
            }
          >
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
          <span className={`badge ${r.source === 'user' ? 'source-rule' : 'source-llm'}`}>{r.source === 'user' ? '직접' : 'AI'}</span>
          <span className="muted small">
            적용 {r.hits}회 · 거래 {r.tx_count}건
          </span>
          <button
            className="danger-text"
            onClick={() =>
              run(async () => {
                await ledgerApi.deleteRule(r.id)
                reload()
              }, '삭제했어요')
            }
          >
            삭제
          </button>
        </div>
      ))}
      {message && <p className="muted small">{message}</p>}
    </article>
  )
}

const EMPTY_GROUP: Omit<RecurringGroup, 'id'> = { name: '', kind: 'expense', icon: '', sort_order: 99 }

function GroupRow({ group, onChange }: { group?: RecurringGroup; onChange: () => void }) {
  const [g, setG] = useState<Omit<RecurringGroup, 'id'>>(
    group ? { name: group.name, kind: group.kind, icon: group.icon, sort_order: group.sort_order } : EMPTY_GROUP,
  )
  const { message, run } = useSaver()
  const save = () =>
    run(async () => {
      if (group) await recurringApi.updateRecurringGroup(group.id, g)
      else {
        await recurringApi.createRecurringGroup(g)
        setG(EMPTY_GROUP)
      }
      onChange()
    })
  const inUse = (group?.item_count ?? 0) > 0
  return (
    <div className="edit-row">
      <IconPicker value={g.icon} onChange={(icon) => setG({ ...g, icon })} />
      <input className="w-name" placeholder="새 정기지출 카테고리" value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} />
      <select
        value={g.kind}
        className={g.kind === 'saving' ? 'amt-saving' : 'amt-fixed'}
        onChange={(e) => setG({ ...g, kind: e.target.value as RecurringKind })}
        aria-label="성격"
      >
        <option value="saving">저금</option>
        <option value="expense">지출</option>
      </select>
      {group && <span className="muted small">항목 {group.item_count ?? 0}개</span>}
      <button disabled={!g.name} onClick={save}>
        {group ? '저장' : '추가'}
      </button>
      {group && (
        <button
          className="danger-text"
          disabled={inUse}
          title={inUse ? '이 카테고리를 쓰는 항목이 있어 삭제할 수 없어요' : undefined}
          onClick={() =>
            confirm(`'${group.name}' 카테고리를 삭제할까요?`) &&
            run(async () => {
              await recurringApi.deleteRecurringGroup(group.id)
              onChange()
            }, '삭제했어요')
          }
        >
          삭제
        </button>
      )}
      {message && <span className="muted small">{message}</span>}
    </div>
  )
}

export function SystemSettings() {
  const readOnly = useReadOnly()
  const { data: info, error, reload } = useLoad(() => systemApi.system(), [])
  const { data: storage, reload: reloadStorage } = useLoad(() => ledgerApi.extractionStorage(), [])
  const { message, run } = useSaver()
  return (
    <>
      {error && <p className="error">{error}</p>}
      {info && (
        <>
          <p className="muted small">
            LLM 고르기는 <Link to="/settings?tab=llm">LLM</Link> 탭, 캡쳐 판독 OCR(Unlimited-OCR-2)은{' '}
            <Link to="/settings?tab=ocr">OCR</Link> 탭에서 볼 수 있어요.
          </p>
          <BanksaladImport />
          <article className="card">
            <h2>캡쳐 판독 기록</h2>
            <p className="muted small">
              판독 정확도를 재기 위해 캡쳐 이미지와 판독 결과(OCR 글 포함)를 서버의 data 폴더에만 보관해요. 이미지를 지워도 기록과 정확도 통계는 남고,
              재평가(<code>make eval</code>)만 할 수 없게 돼요.
            </p>
            {storage && (
              <dl className="kv">
                <dt>판독 기록</dt>
                <dd>{storage.logs.toLocaleString('ko-KR')}건</dd>
                <dt>보관 이미지</dt>
                <dd>
                  {storage.images}장 · {(storage.bytes / 1024 / 1024).toFixed(1)} MB
                </dd>
              </dl>
            )}
            <div className="form-actions">
              {message && <span className="muted small">{message}</span>}
              <button
                className="danger-text"
                disabled={!storage?.images}
                onClick={() =>
                  confirm('보관 중인 캡쳐 이미지를 모두 삭제할까요? 기록과 통계는 남아요.') &&
                  run(async () => {
                    await ledgerApi.deleteExtractionImages()
                    reloadStorage()
                  }, '삭제했어요')
                }
              >
                이미지 전체 삭제
              </button>
            </div>
          </article>
          <article className="card">
            <h2>데이터</h2>
            <dl className="kv">
              <dt>DB 파일</dt>
              <dd className="mono">{info.db.path ?? '—'}</dd>
              <dt>크기</dt>
              <dd>{(info.db.size_bytes / 1024).toFixed(0)} KB</dd>
              <dt>거래 수</dt>
              <dd>{info.db.transactions.toLocaleString('ko-KR')}건</dd>
              <dt>스키마 버전</dt>
              <dd>v{info.db.schema_version}</dd>
            </dl>
            <div className="form-actions">
              <button onClick={reload}>새로고침</button>
              {!readOnly && (
                <a className="button primary" href="/api/system/backup" download>
                  DB 백업 다운로드
                </a>
              )}
            </div>
          </article>
        </>
      )}
    </>
  )
}

const ACTION_LABEL: Record<string, string> = {
  insert: '가져옴',
  duplicate: '이미 있음',
  cancel_pair: '결제 취소 상쇄',
  skip_zero: '0원 건너뜀',
  skip_currency: '외화 건너뜀',
}

/** 뱅크샐러드 가계부 내보내기(xlsx/zip) 가져오기: 파일을 고르면 바로 미리보기 → 확인 후 가져오기, 기록·되돌리기 */
export function BanksaladImport() {
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'preview' | 'import' | null>(null)
  const { data: batches, reload } = useLoad(() => ledgerApi.imports(), [])

  const run = async (target: File, dryRun: boolean) => {
    setBusy(dryRun ? 'preview' : 'import')
    setError(null)
    try {
      setReport(await ledgerApi.importBanksalad(target, dryRun))
      if (!dryRun) reload()
    } catch (e) {
      setError((e as Error).message)
    }
    setBusy(null)
  }
  // 가져오기는 미리보기가 성공한 파일만 — 무엇이 들어올지 먼저 보여준다
  const status = busy === 'preview' ? '미리보기 중…'
    : busy === 'import' ? '가져오는 중…'
      : !file ? '파일을 고르면 미리보기를 보여줘요'
        : error ? '미리보기에 실패했어요 — 파일을 확인하세요'
          : report?.dry_run ? '미리보기를 확인한 뒤 가져오기를 누르세요'
            : report ? '가져오기를 마쳤어요'
              : ''

  return (
    <article className="card">
      <h2>데이터 가져오기 (뱅크샐러드)</h2>
      <p className="muted small">
        뱅크샐러드 앱 &gt; 가계부 내보내기로 받은 엑셀(.xlsx) 또는 압축(.zip, 암호 없음)을 올려요. 결제 취소는 원거래와 상쇄하고, 카드대금·내 계좌 이체는 ±0으로
        처리해요. 같은 파일을 다시 올려도 중복으로 들어가지 않고, 가져오기 단위로 되돌릴 수 있어요.
      </p>
      <div className="edit-row">
        <input
          type="file"
          accept=".xlsx,.zip"
          onChange={(e) => {
            const next = e.target.files?.[0] ?? null
            setFile(next)
            setReport(null)
            setError(null)
            if (next) run(next, true)
          }}
        />
        <button disabled={!file || !!busy} onClick={() => file && run(file, true)}>
          다시 미리보기
        </button>
        <button className="primary" disabled={!file || !!busy || !report?.dry_run} onClick={() => file && run(file, false)}>
          가져오기
        </button>
      </div>
      {status && <p className="muted small">{status}</p>}
      {error && <p className="error small">{error}</p>}
      {report && (
        <div className="import-report">
          <p className="small">
            <b>{report.dry_run ? '미리보기' : `가져오기 #${report.batch_id} 완료`}</b> · {report.rows.toLocaleString('ko-KR')}행
            {report.period && ` · ${report.period.from} ~ ${report.period.to}`}
          </p>
          <p className="muted small">
            {Object.entries(report.actions)
              .map(([k, v]) => `${ACTION_LABEL[k] ?? k} ${v.toLocaleString('ko-KR')}`)
              .join(' · ')}
          </p>
          {!report.dry_run && (
            <p className="small">
              분류 필요 {report.needs_review} · 정기지출 자동 매칭 {report.recurring_matched} · 내 규칙으로 분류 {report.filled_by_rule}
            </p>
          )}
          <table className="data-table">
            <thead>
              <tr>
                <th>뱅크샐러드 → 이 앱</th>
                <th>건수</th>
              </tr>
            </thead>
            <tbody>
              {report.mapping.map((m) => (
                <tr key={m.rule}>
                  <td>{m.rule}</td>
                  <td>{m.count.toLocaleString('ko-KR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {batches && batches.length > 0 && (
        <>
          <h3 className="small">가져오기 기록</h3>
          {batches.map((b) => (
            <div key={b.id} className="edit-row">
              <span className="w-name">
                #{b.id} {b.file_name}
              </span>
              <span className="muted small">
                {b.period_from} ~ {b.period_to} · 거래 {b.tx_count.toLocaleString('ko-KR')}건 · {b.created_at.slice(0, 16)}
              </span>
              <button
                className="danger-text"
                onClick={async () => {
                  if (!confirm(`가져오기 #${b.id}로 들어온 거래 ${b.tx_count}건을 모두 지울까요?`)) return
                  await ledgerApi.undoImport(b.id)
                  setReport(null)
                  reload()
                }}
              >
                되돌리기
              </button>
            </div>
          ))}
        </>
      )}
    </article>
  )
}
