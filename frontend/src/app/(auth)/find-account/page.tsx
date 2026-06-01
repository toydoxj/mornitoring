"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"

interface FindAccountResponse {
  found: boolean
  emails: string[]
  message: string
}

export default function FindAccountPage() {
  const router = useRouter()
  const [name, setName] = useState("")
  const [phone, setPhone] = useState("")
  const [result, setResult] = useState<FindAccountResponse | null>(null)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError("")
    setResult(null)
    setIsSubmitting(true)
    try {
      const { data } = await apiClient.post<FindAccountResponse>(
        "/api/auth/find-account",
        { name, phone }
      )
      setResult(data)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || "아이디 찾기에 실패했습니다")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">아이디 찾기</CardTitle>
          <p className="text-sm text-muted-foreground">
            등록된 이름과 휴대폰번호를 입력해주세요
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">이름</Label>
              <Input
                id="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">휴대폰번호</Label>
              <Input
                id="phone"
                inputMode="tel"
                placeholder="010-0000-0000"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button
              type="submit"
              className="w-full"
              loading={isSubmitting}
              loadingText="확인 중..."
            >
              확인
            </Button>
          </form>

          {result && (
            <div
              className={
                result.found
                  ? "rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800"
                  : "rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
              }
            >
              <p className="font-medium">{result.message}</p>
              {result.emails.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {result.emails.map((email) => (
                    <li key={email} className="font-mono">
                      {email}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
            <p>비밀번호 재설정은 관리자에게 문의해주세요.</p>
          </div>

          <Button variant="outline" className="w-full" onClick={() => router.push("/login")}>
            로그인 화면으로
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
