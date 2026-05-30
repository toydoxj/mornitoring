"use client"

import { useState } from "react"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import apiClient from "@/lib/api/client"

interface BulkTokenRefreshSummary {
  total: number
  refreshed: number
  skipped: number
  failed: number
}

interface BulkTokenRefreshResult {
  user_id: number
  name: string
  status_before: string
  status_after: string
  kakao_token_expires_at: string | null
  refreshed: boolean
  error: string | null
}

interface BulkTokenRefreshResponse {
  summary: BulkTokenRefreshSummary
  results: BulkTokenRefreshResult[]
}

interface KakaoTokenBulkRefreshButtonProps {
  refreshNeededCount: number
  onRefreshed: () => Promise<void> | void
  className?: string
}

export function KakaoTokenBulkRefreshButton({
  refreshNeededCount,
  onRefreshed,
  className,
}: KakaoTokenBulkRefreshButtonProps) {
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [result, setResult] = useState<BulkTokenRefreshResponse | null>(null)

  const handleRefresh = async () => {
    if (
      refreshNeededCount === 0
      && !confirm("갱신 필요한 토큰이 없습니다. 그래도 전체 점검을 실행할까요?")
    ) {
      return
    }

    setIsRefreshing(true)
    setResult(null)
    try {
      const { data } = await apiClient.post<BulkTokenRefreshResponse>(
        "/api/kakao/tokens/refresh"
      )
      setResult(data)
      await onRefreshed()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "토큰 일괄 갱신 실패"
      alert(msg)
    } finally {
      setIsRefreshing(false)
    }
  }

  const failedNames =
    result?.results
      .filter((item) => item.error)
      .slice(0, 3)
      .map((item) => item.name)
      .join(", ") ?? ""

  return (
    <div className={className ?? "flex flex-col items-end gap-1"}>
      <Button
        variant="outline"
        onClick={handleRefresh}
        loading={isRefreshing}
        loadingText="갱신 중..."
        title="만료 임박 또는 만료된 카카오 토큰을 refresh token으로 갱신"
      >
        <RefreshCw />
        토큰 일괄 갱신
        {refreshNeededCount > 0 && ` (${refreshNeededCount})`}
      </Button>
      {result && (
        <p
          className={
            result.summary.failed > 0
              ? "text-xs text-red-700"
              : "text-xs text-muted-foreground"
          }
        >
          갱신 {result.summary.refreshed}명 · 건너뜀 {result.summary.skipped}명 · 실패{" "}
          {result.summary.failed}명
          {failedNames && ` (${failedNames})`}
        </p>
      )}
    </div>
  )
}
