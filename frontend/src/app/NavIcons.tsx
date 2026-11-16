/** 사이드바 아이콘 (선 아이콘, currentColor) */
import type { ReactNode } from 'react'

const Svg = ({ children }: { children: ReactNode }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

export const HomeIcon = () => (
  <Svg>
    <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
  </Svg>
)

export const LedgerIcon = () => (
  <Svg>
    <path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" />
    <path d="M9 8h6M9 12h6M9 16h3" />
  </Svg>
)

export const RecurringIcon = () => (
  <Svg>
    <path d="M17 2l3 3-3 3" />
    <path d="M4 11V9a4 4 0 0 1 4-4h12" />
    <path d="M7 22l-3-3 3-3" />
    <path d="M20 13v2a4 4 0 0 1-4 4H4" />
  </Svg>
)

/** 예산 배정: 길이가 다른 막대 셋 */
export const BudgetIcon = () => (
  <Svg>
    <path d="M4 6h11M4 12h16M4 18h7" />
    <circle cx="18" cy="6" r="1.6" />
    <circle cx="14" cy="18" r="1.6" />
  </Svg>
)

export const InvestIcon = () => (
  <Svg>
    <path d="M3 17l6-6 4 4 8-8" />
    <path d="M14 7h7v7" />
  </Svg>
)

export const LabIcon = () => (
  <Svg>
    <path d="M9 3h6M10 3v6L4.6 18.7A1.5 1.5 0 0 0 5.9 21h12.2a1.5 1.5 0 0 0 1.3-2.3L14 9V3" />
    <path d="M7.5 15h9" />
  </Svg>
)

export const SettingsIcon = () => (
  <Svg>
    <path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" />
    <circle cx="15" cy="6" r="2" />
    <circle cx="9" cy="12" r="2" />
    <circle cx="17" cy="18" r="2" />
  </Svg>
)

export const PortfolioIcon = () => (
  <Svg>
    <path d="M12 3a9 9 0 1 0 9 9h-9z" />
    <path d="M15 3.5A9 9 0 0 1 20.5 9H15z" />
  </Svg>
)

export const AiIcon = () => (
  <Svg>
    <path d="M4 5h16v11H9l-5 4z" />
    <path d="M12 8.2l.8 1.8 1.8.8-1.8.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8z" />
  </Svg>
)

/** 소비 습관 (전구) */
export const InsightsIcon = () => (
  <Svg>
    <path d="M9 18h6M10 21h4" />
    <path d="M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1V16h5v-.1c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z" />
  </Svg>
)

/** 급여: 지폐와 원 */
export const SalaryIcon = () => (
  <Svg>
    <rect x="2.5" y="6" width="19" height="12" rx="2" />
    <circle cx="12" cy="12" r="2.6" />
    <path d="M6 9.5v5M18 9.5v5" />
  </Svg>
)
