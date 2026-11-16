import type { CategorySource } from './api'

const LABEL: Record<CategorySource, { text: string; title: string }> = {
  rule: { text: '🔁 내 규칙', title: '전에 직접 고른 분류를 가맹점 규칙으로 적용했어요' },
  llm: { text: '✨ AI 분류', title: 'AI가 추정한 분류예요. 고치면 다음부터 규칙으로 적용돼요' },
  user: { text: '직접 분류', title: '직접 고른 분류예요' },
  import: { text: '📥 뱅크샐러드', title: '뱅크샐러드에서 가져온 분류예요. 고치면 다음부터 내 규칙으로 적용돼요' },
}

/** 카테고리 분류 출처 배지 */
export default function SourceBadge({ source }: { source: CategorySource }) {
  const { text, title } = LABEL[source]
  return (
    <span className={`badge source-${source}`} title={title}>
      {text}
    </span>
  )
}
