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
      await apiClient.post("/api/auth/password-setup", {
        token,
        new_password: newPassword,
      })
      setStage("done")
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "비밀번호 설정 실패")
    } finally {
      setIsSubmitting(false)
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
          <Button className="w-full" onClick={() => router.push("/login")}>
            로그인하러 가기
          </Button>
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
