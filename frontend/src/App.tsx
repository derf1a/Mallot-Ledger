import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import Layout, { type ViewerActions } from './app/Layout'
import { authApi, goHomeLogin, homeLogout, type Me } from './features/auth/api'
import LoginPage from './features/auth/LoginPage'
import { setReadOnly, UNAUTHORIZED_EVENT } from './shared/http'
import { ReadOnlyContext } from './shared/readOnly'

// 무거운 화면(차트 · 분석 · 설정)은 처음 열 때 불러온다 — 첫 화면 번들을 작게
const Home = lazy(() => import('./features/home/HomePage'))
const Ledger = lazy(() => import('./features/ledger/LedgerPage'))
const Budget = lazy(() => import('./features/budget/BudgetPage'))
const Recurring = lazy(() => import('./features/recurring/RecurringPage'))
const Salary = lazy(() => import('./features/salary/SalaryPage'))
const Insights = lazy(() => import('./features/insights/InsightsPage'))
const Settings = lazy(() => import('./features/settings/SettingsPage'))

const page = (el: ReactNode) => <Suspense fallback={<p className="muted">불러오는 중…</p>}>{el}</Suspense>

/**
 * 역할에 따라: 관리자 = 모든 화면, 손님(공유 링크) = 같은 화면을 읽기만(키 · 공유 설정 없음, 쓰기는 화면 · 서버 둘 다 막음),
 * 아무도 아님 = 공유 링크 입장 또는 관리자 로그인.
 * 로그인이 꺼진 모드(이 컴퓨터에서만 쓰기)에서는 서버가 언제나 관리자로 답한다.
 * 홈 모드(me.home)면 로그인 · 로그아웃 · 손님 공유는 Mallot 홈에서 — 로그인 폼 대신 홈 로그인으로 보낸다.
 */
export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => authApi.me().then(setMe).catch((e: Error) => setError(e.message)), [])
  useEffect(() => { load() }, [load])
  // 쓰는 중에 로그인이 풀리면(7일 만료 · 비밀번호 변경 · 공유 키 교체) API 가 401 → 역할을 다시 읽어 로그인 화면으로
  useEffect(() => {
    const onUnauthorized = () => { load() }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [load])
  const home = Boolean(me?.home)
  const logout = useCallback(() => (me?.home ? homeLogout(me) : authApi.logout().finally(load)), [me, load])
  const readOnly = me?.role === 'viewer'
  useEffect(() => { setReadOnly(readOnly) }, [readOnly])
  const signedOut = Boolean(me && me.role !== 'admin' && me.role !== 'viewer')
  useEffect(() => { if (me && home && signedOut) goHomeLogin(me) }, [me, home, signedOut])

  if (error) return <p className="error page-error">{error}</p>
  if (!me) return <p className="muted page-error">불러오는 중…</p>
  if (me.role === 'admin' || me.role === 'viewer') {
    const viewer = readOnly
      ? { onLogin: () => (home ? goHomeLogin(me) : setMe({ ...me, role: null })), onLeave: logout }
      : undefined
    return (
      <ReadOnlyContext.Provider value={readOnly}>
        <MainApp onLogout={me.auth && !readOnly ? logout : undefined} viewer={viewer} />
      </ReadOnlyContext.Provider>
    )
  }
  if (home) return <p className="muted page-error">Mallot 홈 로그인으로 가는 중…</p>
  return <Gate me={me} onDone={load} />
}

function MainApp({ onLogout, viewer }: { onLogout?: () => void; viewer?: ViewerActions }) {
  return (
    <Routes>
      <Route element={<Layout onLogout={onLogout} viewer={viewer} />}>
        <Route index element={page(<Home />)} />
        <Route path="ledger" element={page(<Ledger />)} />
        <Route path="ledger/budget" element={page(<Budget />)} />
        <Route path="ledger/recurring" element={page(<Recurring />)} />
        <Route path="ledger/insights" element={page(<Insights />)} />
        <Route path="salary" element={page(<Salary />)} />
        <Route path="settings" element={page(<Settings />)} />
        <Route path="recurring" element={<Navigate to="/ledger/recurring" replace />} />
        <Route path="insights" element={<Navigate to="/ledger/insights" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

/** 로그인 전: /share?k=… 이면 손님으로 들어가고, 아니면 관리자 로그인 */
function Gate({ me, onDone }: { me: Me; onDone: () => Promise<unknown> }) {
  const location = useLocation()
  const navigate = useNavigate()
  const key = location.pathname === '/share' ? new URLSearchParams(location.search).get('k') : null
  const [entering, setEntering] = useState(Boolean(key))
  const [failed, setFailed] = useState<string | null>(null)
  useEffect(() => {
    if (!key) return
    authApi.enter(key)
      .then(() => {
        // 주소창 · 라우터 둘 다에서 키를 지운다 — 남아 있으면 "관리자 로그인"을 눌러도 이 키로 다시 손님 입장한다
        navigate('/', { replace: true })
        return onDone()
      })
      .catch((e: Error) => setFailed(e.message))
      .finally(() => setEntering(false))  // 손님이 되면 이 화면은 사라진다. 쿠키가 막혀 그대로면 로그인 화면으로
  }, [key, onDone, navigate])
  if (entering) return <p className="muted page-error">들어가는 중…</p>
  return (
    <>
      {failed && <p className="error page-error">{failed}</p>}
      <LoginPage me={me} onDone={onDone} />
    </>
  )
}
