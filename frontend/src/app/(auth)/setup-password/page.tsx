"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"

type ValidateResponse = {
  valid: boolean
  purpose: string
  email_masked: string
}

type Stage = "loading" | "form" | "invalid" | "done"

function SetupPasswordContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get("token") || ""

  const [stage, setStage] = useState<Stage>("loading")
  const [emailMasked, setEmailMasked] = useState("")
  const [purpose, setPurpose] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [kakaoAlreadyLinked, setKakaoAlreadyLinked] = useState(false)

  useEffect(() => {
    if (!token) {
      setStage("invalid")
      return
    }
    let cancelled = false
    const validate = async () => {
      try {
        const { data } = await apiClient.get<ValidateResponse>(
          "/api/auth/password-setup/validate",
          { params: { token } }
        )
        if (cancelled) return
        if (data.valid) {
          setEmailMasked(data.email_masked)
          setPurpose(data.purpose)
          setStage("form")
        } else {
          setStage("invalid")
        }
      } catch {
        if (!cancelled) setStage("invalid")
      }
    }
    validate()
    return () => {
      cancelled = true
    }
  }, [token])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (newPassword.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다")
      return
    }
    if (newPassword !== confirmPassword) {
      setError("비밀번호가 일치하지 않습니다")
      return
    }
    setIsSubmitting(true)
    try {
      const { data } = await apiClient.post<{
        message: string
        email?: string
        kakao_linked?: boolean
      }>("/api/auth/password-setup", {
        token,
        new_password: newPassword,
      })
      // 카카오 OAuth /link-account 단계에서 이메일 prefill에 사용
      // (비밀번호는 저장하지 않음 — 사용자가 다시 입력)
      if (data.email) {
        sessionStorage.setItem("pending_link_email", data.email)
      }
      setKakaoAlreadyLinked(!!data.kakao_linked)
      setStage("done")
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "비밀번호 설정 실패")
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleConnectKakao = async () => {
    try {
      const { data } = await apiClient.get<{ url: string }>("/api/auth/kakao/login")
      window.location.href = data.url
    } catch {
      // 카카오 URL 조회 실패 시 로그인 화면으로 fallback
      router.push("/login")
    }
  }

  if (stage === "loading") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>링크 확인 중...</CardTitle>
        </CardHeader>
      </Card>
    )
  }

  if (stage === "invalid") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-lg">유효하지 않은 링크</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-center text-sm text-muted-foreground">
          <p>링크가 만료되었거나 이미 사용되었습니다.</p>
          <p>관리자에게 새 초대 발송을 요청해주세요.</p>
          <Button variant="outline" onClick={() => router.push("/login")}>
            로그인 화면으로
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (stage === "done") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-lg">비밀번호 설정 완료</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-center text-sm text-muted-foreground">
          <p>이제 새 비밀번호로 로그인할 수 있습니다.</p>
          {kakaoAlreadyLinked ? (
            <Button className="w-full" onClick={() => router.push("/login")}>
              로그인하러 가기
            </Button>
          ) : (
            <>
              <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800">
                카카오 알림을 받으려면 다음 단계에서 카카오 로그인 + 동의가 필요합니다.
              </p>
              <Button className="w-full" onClick={handleConnectKakao}>
                지금 카카오 연동하기
              </Button>
              <Button variant="outline" className="w-full" onClick={() => router.push("/login")}>
                나중에 하기 (로그인 화면으로)
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <CardTitle className="text-2xl">비밀번호 설정</CardTitle>
        <p className="text-sm text-muted-foreground">
          {purpose === "password_reset"
            ? "새 비밀번호를 입력해주세요"
            : "최초 비밀번호를 설정해주세요"}
        </p>
        <p className="text-xs text-muted-foreground">계정: {emailMasked}</p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="new">새 비밀번호 (8자 이상)</Label>
            <Input
              id="new"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">비밀번호 확인</Label>
            <Input
              id="confirm"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button
            type="submit"
            className="w-full"
            loading={isSubmitting}
            loadingText="설정 중..."
          >
            비밀번호 설정
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

export default function SetupPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Suspense
        fallback={
          <Card className="w-full max-w-md">
            <CardHeader className="text-center">
              <CardTitle>로딩 중...</CardTitle>
            </CardHeader>
          </Card>
        }
      >
        <SetupPasswordContent />
      </Suspense>
    </div>
  )
}
