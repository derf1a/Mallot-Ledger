import { useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { systemApi } from '../features/settings/api'
import { pathMode } from '../shared/otherApp'
import { useLoad } from '../shared/useLoad'
import AccessAlerts from './AccessAlerts'
import AppMark from './AppMark'
import AppSwitcher from './AppSwitcher'
import { BudgetIcon, HomeIcon, InsightsIcon, LedgerIcon, LogoutIcon, RecurringIcon, SalaryIcon, SettingsIcon } from './NavIcons'

interface NavItem {
  to: string
  label: string
  icon: ReactNode
}

interface NavSection {
  title: string
  items: NavItem[]
}

/**
 * 메뉴 — Overview: 한눈에(대시보드) · Spend: 한 달의 돈(지출 내역 · 변동비 예산 · 고정비) · Income: 급여 · Analyze: 소비 분석.
 * 맨 아래 작게 설정.
 */
const SECTIONS: NavSection[] = [
  { title: 'Overview', items: [{ to: '/', label: 'Home', icon: <HomeIcon /> }] },
  {
    title: 'Spend',
    items: [
      { to: '/ledger', label: 'Spending', icon: <LedgerIcon /> },
      { to: '/ledger/budget', label: 'Budget', icon: <BudgetIcon /> },
      { to: '/ledger/recurring', label: 'Fixed', icon: <RecurringIcon /> },
    ],
  },
  { title: 'Income', items: [{ to: '/salary', label: 'Salary', icon: <SalaryIcon /> }] },
  { title: 'Analyze', items: [{ to: '/ledger/insights', label: 'Insights', icon: <InsightsIcon /> }] },
]
const UTILITY: NavItem[] = [{ to: '/settings', label: 'Settings', icon: <SettingsIcon /> }]
// 경로 모드(한 도메인의 /ledger/)면 Mallot 홈 로그인을 같이 쓴다, 하위 도메인 · 포트면 앱마다 따로
const SWITCH_NOTE = pathMode() ? 'Mallot 홈 로그인을 같이 써요' : '로그인은 따로예요'

function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wm-m">M</span>
      <span className="wm-allot">allot</span>
      <span className="wm-sub">ledger</span>
    </span>
  )
}

/** 손님(공유 링크)으로 볼 때 — 읽기 전용 표시와 관리자 로그인 · 나가기 */
export interface ViewerActions { onLogin: () => void; onLeave: () => void }

// PC: 왼쪽 사이드바 고정 / 모바일: 좌상단 햄버거 버튼으로 여닫는 드로어
export default function Layout({ onLogout, viewer }: { onLogout?: () => void; viewer?: ViewerActions }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const { data: health } = useLoad(() => systemApi.health().catch(() => null), [])
  const all = [...SECTIONS.flatMap((s) => s.items), ...UTILITY]
  const current = all.find((item) => item.to === location.pathname)
  const link = (item: NavItem, kind: '' | 'small' = '') => (
    <NavLink key={item.to} to={item.to} end className={`nav-link${kind ? ` ${kind}` : ''}`} onClick={() => setMenuOpen(false)}>
      <span className="nav-icon">{item.icon}</span>
      <span>{item.label}</span>
    </NavLink>
  )

  return (
    <div className="app">
      <header className="topbar">
        <button className="menu-button" aria-label="메뉴 열기" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
          ☰
        </button>
        <AppMark app="ledger" size={24} />
        <span className="topbar-title">{current?.label ?? 'Mallot Ledger'}</span>
        {viewer && <span className="chip readonly-chip">읽기 전용</span>}
      </header>

      {menuOpen && <div className="backdrop" onClick={() => setMenuOpen(false)} />}

      <nav className={`sidebar${menuOpen ? ' open' : ''}`}>
        <NavLink to="/" className="brand" onClick={() => setMenuOpen(false)}>
          <AppMark app="ledger" />
          <Wordmark />
        </NavLink>
        <div className="nav-main">
          {SECTIONS.map((s) => (
            <div key={s.title} className="nav-group">
              <span className="nav-section">{s.title}</span>
              {s.items.map((item) => link(item))}
            </div>
          ))}
        </div>
        <div className="nav-utility">
          {UTILITY.map((item) => link(item, 'small'))}
          {viewer && (
            <>
              <span className="nav-readonly small">읽기 전용 · 손님</span>
              <button className="nav-link small nav-button" onClick={viewer.onLogin}>관리자 로그인</button>
              <button className="nav-link small nav-button" onClick={viewer.onLeave}>나가기</button>
            </>
          )}
        </div>
        <AppSwitcher self="ledger" note={SWITCH_NOTE} />
        <footer className="sidebar-footer">
          <span className="footer-text" title={`Mallot Ledger v${__APP_VERSION__} · build ${__GIT_SHA__}${health ? ` · DB 스키마 v${health.db_version}` : ''}`}>
            v{__APP_VERSION__} · {__GIT_SHA__}
            {health && ` · db v${health.db_version}`}
          </span>
          {onLogout && (
            <button className="footer-logout" onClick={onLogout} title="로그아웃" aria-label="로그아웃">
              <LogoutIcon />
            </button>
          )}
        </footer>
      </nav>

      <main className="content">
        {!viewer && <AccessAlerts />}
        <Outlet />
      </main>
    </div>
  )
}
