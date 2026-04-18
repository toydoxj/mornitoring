"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"

function LinkAccountContent() {
  const router = useRouter()
  const fetchMe = useAuthStore((s) => s.fetchMe)

  const [linkSessionId, setLinkSessionId] = useState("")
  const [kakaoName, setKakaoName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    const sessionId = sessionStorage.getItem("kakao_link_session_id") || ""
    if (!sessionId) {
      router.replace("/login")
      return
    }
    setLinkSessionId(sessionId)
    setKakaoName(sessionStorage.getItem("kakao_link_name") || "")
    // 비번 셋팅 직후 카카오 OAuth로 자동 이동한 케이스: 이메일 자동 채움
    const pendingEmail = sessionStorage.getItem("pending_link_email")
    if (pendingEmail) {
      setEmail(pendingEmail)
      sessionStorage.removeItem("pending_link_email")
    }
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      const { data } = await apiClient.post("/api/auth/link-account", {
        email,
        password,
        link_session_id: linkSessionId,
      })

      sessionStorage.removeItem("kakao_link_session_id")
      sessionStorage.removeItem("kakao_link_name")
      localStorage.setItem("access_token", data.access_token)
      await fetchMe()
      router.push("/dashboard")
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "계정 연결 실패")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">계정 연결</CardTitle>
        <p className="text-sm text-muted-foreground">
          카카오 계정{kakaoName && ` (${kakaoName})`}과 기존 계정을 연결합니다
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="rounded-md bg-muted p-3 text-sm">
            <p>카카오 닉네임과 일치하는 계정을 찾지 못했습니다.</p>
            <p>기존 계정의 이메일과 비밀번호를 입력하여 연결해주세요.</p>
            <p className="mt-1 text-muted-foreground">한번 연결하면 이후 카카오 로그인만으로 접속됩니다.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">이메일</Label>
            <Input
              id="email"
              type="email"
              placeholder="등록된 이메일 주소"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">비밀번호</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button type="submit" className="w-full" loading={isSubmitting} loadingText="연결 중...">
            계정 연결
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="w-full"
            onClick={() => router.push("/login")}
          >
            다른 방법으로 로그인
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

export default function LinkAccountPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Suspense fallback={
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>로딩 중...</CardTitle>
          </CardHeader>
        </Card>
      }>
        <LinkAccountContent />
      </Suspense>
    </div>
  )
}
