"use client"

import { useState } from "react"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import apiClient from "@/lib/api/client"

interface BulkLoginUuidSyncSummary {
  total: number
  synced: number
  matched: number
  mismatched: number
  failed: number
}

interface BulkLoginUuidSyncResult {
  user_id: number
  name: string
  status_before: string
  status_after: string
  synced: boolean
  error: string | null
}

interface BulkLoginUuidSyncResponse {
  summary: BulkLoginUuidSyncSummary
  results: BulkLoginUuidSyncResult[]
}

interface KakaoIdentitySyncButtonProps {
  unknownCount: number
  onSynced: () => Promise<void> | void
  className?: string
}

export function KakaoIdentitySyncButton({
  unknownCount,
  onSynced,
  className,
}: KakaoIdentitySyncButtonProps) {
  const [isSyncing, setIsSyncing] = useState(false)
  const [result, setResult] = useState<BulkLoginUuidSyncResponse | null>(null)

  const handleSync = async () => {
    if (
      unknownCount === 0
      && !confirm("확인불가 사용자가 없습니다. 그래도 전체 동기화를 실행할까요?")
    ) {
      return
    }

    setIsSyncing(true)
    setResult(null)
    try {
      const { data } = await apiClient.post<BulkLoginUuidSyncResponse>(
        "/api/kakao/login-uuids/sync"
      )
      setResult(data)
      await onSynced()
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "카카오 일치 확인 동기화 실패"
      alert(msg)
    } finally {
      setIsSyncing(false)
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
        onClick={handleSync}
        loading={isSyncing}
        loadingText="확인 중..."
        title="저장된 카카오 토큰으로 로그인 UUID를 조회해 친구 매칭 UUID와 비교"
      >
        <RefreshCw />
        일치 확인 동기화
        {unknownCount > 0 && ` (${unknownCount})`}
      </Button>
      {result && (
        <p
          className={
            result.summary.failed > 0 || result.summary.mismatched > 0
              ? "text-xs text-red-700"
              : "text-xs text-muted-foreground"
          }
        >
          동기화 {result.summary.synced}명 · 일치 {result.summary.matched}명 · 불일치{" "}
          {result.summary.mismatched}명 · 실패 {result.summary.failed}명
          {failedNames && ` (${failedNames})`}
        </p>
      )}
    </div>
  )
}
