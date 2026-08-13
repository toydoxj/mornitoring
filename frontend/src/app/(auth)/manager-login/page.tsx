"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthStore } from "@/stores/authStore"

export default function ManagerLoginPage() {
  const router = useRouter()
  const login = useAuthStore((s) => s.login)

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    const trimmedEmail = email.trim()
    if (!trimmedEmail || !password) {
      setError("이메일과 비밀번호를 입력해주세요")
      return
    }

    setIsSubmitting(true)
    try {
      const { mustChangePassword } = await login(trimmedEmail, password, {
        manager: true,
      })
      router.push(mustChangePassword ? "/change-password" : "/dashboard")
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "로그인에 실패했습니다")
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">관리원 로그인</CardTitle>
          <p className="text-sm text-muted-foreground">
            건축구조안전 모니터링 · 이메일과 비밀번호로 로그인하세요
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">이메일</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">비밀번호</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="비밀번호"
              />
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}

            <Button
              type="submit"
              className="w-full"
              loading={isSubmitting}
              loadingText="로그인 중..."
            >
              로그인
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            관리원 전용 화면입니다. 다른 계정은{" "}
            <a href="/login" className="underline hover:text-foreground">
              기본 로그인
            </a>
            을 이용해주세요.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
