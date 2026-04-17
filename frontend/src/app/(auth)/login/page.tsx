"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthStore } from "@/stores/authStore"
import apiClient from "@/lib/api/client"

export default function LoginPage() {
  const router = useRouter()
  const login = useAuthStore((s) => s.login)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleKakaoLogin = async () => {
    try {
      const { data } = await apiClient.get("/api/auth/kakao/login")
      window.location.href = data.url
    } catch {
      setError("카카오 로그인 연결에 실패했습니다")
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      const result = await login(email, password)
      if (result.mustChangePassword) {
        router.push("/change-password")
      } else {
        router.push("/dashboard")
      }
    } catch {
      setError("이메일 또는 비밀번호가 올바르지 않습니다")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">건축구조안전 모니터링</CardTitle>
          <p className="text-sm text-muted-foreground">
            계정 정보를 입력하여 로그인하세요
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">이메일</Label>
              <Input
                id="email"
                type="email"
                placeholder="email@example.com"
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
            {error && (
              <p className="text-sm text-red-500">{error}</p>
            )}
            <Button type="submit" className="w-full" loading={isSubmitting} loadingText="로그인 중...">
              로그인
            </Button>
          </form>
          <div className="mt-4 space-y-2">
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-white px-2 text-muted-foreground">또는</span>
              </div>
            </div>
            <Button
              variant="outline"
              className="w-full bg-[#FEE500] text-[#191919] hover:bg-[#FDD835] border-[#FEE500]"
              onClick={handleKakaoLogin}
            >
              카카오 로그인
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
