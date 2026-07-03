"use client"

import { Suspense, useEffect, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"

type KakaoReconnectLoginResponse = {
  url: string
  user_name: string
}

function KakaoReconnectContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get("token") || ""
  const started = useRef(false)
  const [status, setStatus] = useState("카카오 로그인 재연결 준비 중...")
  const [error, setError] = useState("")
  const displayStatus = token ? status : "재연결 링크를 확인할 수 없습니다"
  const displayError = token ? error : "관리자에게 새 재연결 링크를 요청해주세요."

  useEffect(() => {
    if (started.current) return
    if (!token) {
      return
    }
    started.current = true

    const startReconnect = async () => {
      try {
        const { data } = await apiClient.get<KakaoReconnectLoginResponse>(
          "/api/auth/kakao/reconnect-login",
          { params: { token } },
        )
        setStatus(`${data.user_name}님 카카오 계정 확인으로 이동합니다`)
        window.location.href = data.url
      } catch (err: unknown) {
        const detail =
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          ?? "재연결 링크 처리에 실패했습니다"
        setStatus("재연결 링크를 사용할 수 없습니다")
        setError(detail)
      }
    }

    void startReconnect()
  }, [token])

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-xl">{displayStatus}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-center">
        {displayError ? (
          <>
            <p className="text-sm text-red-600">{displayError}</p>
            <Button variant="outline" onClick={() => router.push("/login")}>
              로그인 화면으로 이동
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">잠시만 기다려주세요...</p>
        )}
      </CardContent>
    </Card>
  )
}

export default function KakaoReconnectPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <Suspense fallback={
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>카카오 로그인 재연결 준비 중...</CardTitle>
          </CardHeader>
        </Card>
      }>
        <KakaoReconnectContent />
      </Suspense>
    </div>
  )
}
