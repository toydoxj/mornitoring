"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"

function KakaoCallbackContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [status, setStatus] = useState("카카오 로그인 처리 중...")
  const fetchMe = useAuthStore((s) => s.fetchMe)

  useEffect(() => {
    const code = searchParams.get("code")
    if (!code) {
      setStatus("인가 코드가 없습니다")
      return
    }

    const handleCallback = async () => {
      try {
        const { data } = await apiClient.get(`/api/auth/kakao/callback?code=${code}`)
        localStorage.setItem("access_token", data.access_token)
        await fetchMe()

        if (data.must_change_password) {
          router.push("/change-password")
        } else {
          const user = useAuthStore.getState().user
          if (user?.role === "reviewer") {
            router.push("/my-reviews")
          } else {
            router.push("/buildings")
          }
        }
      } catch (err: unknown) {
        const axiosErr = err as { response?: { data?: { detail?: string } } }
        const detail = axiosErr.response?.data?.detail || "알 수 없는 오류"
        setStatus(`카카오 로그인 실패: ${detail}`)
      }
    }

    handleCallback()
  }, [searchParams, router, fetchMe])

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle>{status}</CardTitle>
      </CardHeader>
      <CardContent className="text-center text-muted-foreground">
        <p>잠시만 기다려주세요...</p>
      </CardContent>
    </Card>
  )
}

export default function KakaoCallbackPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Suspense fallback={
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>카카오 로그인 처리 중...</CardTitle>
          </CardHeader>
        </Card>
      }>
        <KakaoCallbackContent />
      </Suspense>
    </div>
  )
}
