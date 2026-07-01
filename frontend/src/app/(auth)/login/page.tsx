"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"

async function fetchKakaoLoginUrl(consent = false) {
  const endpoint = consent
    ? "/api/auth/kakao/login?consent=true"
    : "/api/auth/kakao/login"
  const { data } = await apiClient.get<{ url: string }>(endpoint)
  return data.url
}

export default function LoginPage() {
  const kakaoAutoStarted = useRef(false)
  const [error, setError] = useState("")
  const [isKakaoRedirecting, setIsKakaoRedirecting] = useState(false)

  const handleKakaoLogin = useCallback(async (consent = false) => {
    setError("")
    setIsKakaoRedirecting(true)
    try {
      window.location.href = await fetchKakaoLoginUrl(consent)
    } catch {
      setError("카카오 로그인 연결에 실패했습니다")
      setIsKakaoRedirecting(false)
    }
  }, [])

  useEffect(() => {
    if (kakaoAutoStarted.current) return
    const params = new URLSearchParams(window.location.search)
    if (params.get("kakao") !== "consent") return

    kakaoAutoStarted.current = true
    void fetchKakaoLoginUrl(true)
      .then((url) => {
        window.location.href = url
      })
      .catch(() => {
        setError("카카오 로그인 연결에 실패했습니다")
      })
  }, [])

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">건축구조안전 모니터링</CardTitle>
          <p className="text-sm text-muted-foreground">
            카카오 계정으로 로그인하세요
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="outline"
            className="w-full bg-[#FEE500] text-[#191919] hover:bg-[#FDD835] border-[#FEE500]"
            loading={isKakaoRedirecting}
            loadingText="카카오로 이동 중..."
            onClick={() => handleKakaoLogin()}
          >
            카카오 로그인
          </Button>
          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
