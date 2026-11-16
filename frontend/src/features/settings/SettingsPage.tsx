/**
 * 설정 — 개인설정(이름 · 월 주수입 · 수입일 · 내 계좌) · 가계부(카테고리 · 정기지출 칸 · 가맹점 규칙) · 데이터(뱅크샐러드 가져오기 ·
 * 판독 기록 · DB 백업) · OCR(Unlimited-OCR-2) · LLM(기본 LLM · 경로 · vLLM) · 공유 · 접근.
 * 손님(읽기 전용)은 값을 보기만 한다 — 입력 · 버튼을 모두 잠그고, 공유 탭 · DB 백업 · 서버 주소는 없다.
 */
import { useSearchParams } from 'react-router-dom'
import { useReadOnly } from '../../shared/readOnly'
import { LedgerSettings, PersonalSettings, SystemSettings } from './LedgerTabs'
import LlmSettings from './LlmSettings'
import OcrSettings from './OcrSettings'
import RoutesSettings from './RoutesSettings'
import ShareSettings from './ShareSettings'

const TABS = [
  { key: 'personal', label: '개인설정', admin: false },
  { key: 'ledger', label: '가계부설정', admin: false },
  { key: 'data', label: '데이터 · 가져오기', admin: false },
  { key: 'ocr', label: 'OCR', admin: false },
  { key: 'llm', label: 'LLM', admin: false },
  { key: 'share', label: '공유 · 접근', admin: true },
] as const

export default function SettingsPage() {
  const readOnly = useReadOnly()
  const [params, setParams] = useSearchParams()
  const tabs = TABS.filter((t) => !readOnly || !t.admin)
  const tab = tabs.find((t) => t.key === params.get('tab'))?.key ?? 'personal'
  return (
    <div className="page">
      <h1>Settings</h1>
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? 'on' : ''}
            onClick={() => setParams({ tab: t.key })}>
            {t.label}
          </button>
        ))}
      </div>
      {readOnly && <p className="readonly-banner small">읽기 전용 — 설정값을 볼 수만 있어요. 공유 설정 · DB 백업 · 서버 주소는 관리자만 봐요.</p>}
      <fieldset className="readonly-fieldset" disabled={readOnly}>
        {tab === 'personal' ? <PersonalSettings />
          : tab === 'ledger' ? <LedgerSettings />
            : tab === 'data' ? <SystemSettings />
              : tab === 'ocr' ? <OcrSettings />
                : tab === 'llm' ? <><LlmSettings /><RoutesSettings /></>
                  : <ShareSettings />}
      </fieldset>
    </div>
  )
}
