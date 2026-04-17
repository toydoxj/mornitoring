"use client"

import { useEffect } from "react"
import { useRouter, usePathname } from "next/navigation"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { useAuthStore } from "@/stores/authStore"
import { ROLE_LABELS } from "@/types"
import apiClient from "@/lib/api/client"

const SCOPE_CHECK_ROLES = ["team_leader", "chief_secretary", "secretary"]
const SCOPE_CHECK_FLAG = "kakao_scope_checked"

const NAV_ITEMS = [
  { href: "/dashboard", label: "대시보드", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/buildings", label: "통합관리대장", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/distribution", label: "도서접수/배포", roles: ["team_leader", "chief_secretary"] },
  { href: "/my-reviews", label: "내 검토 대상", roles: ["chief_secretary", "secretary", "reviewer"] },
  { href: "/review-files", label: "검토서 관리", roles: ["team_leader", "chief_secretary"] },
  { href: "/inquiries", label: "문의사항", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/inappropriate-review", label: "부적합 검토", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/notifications", label: "알림 현황", roles: ["team_leader", "chief_secretary"] },
  { href: "/admin", label: "사용자 관리", roles: ["team_leader", "chief_secretary"] },
] as const

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isLoading, fetchMe, logout } = useAuthStore()

  useEffect(() => {
    fetchMe()
  }, [fetchMe])

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login")
    }
  }, [isLoading, user, router])

  // 카카오 scope 자동 체크 — 메시지 발송 권한이 필요한 역할만, 세션당 1회
  useEffect(() => {
    if (!user || !user.kakao_linked) return
    if (!SCOPE_CHECK_ROLES.includes(user.role)) return
    if (sessionStorage.getItem(SCOPE_CHECK_FLAG)) return

    sessionStorage.setItem(SCOPE_CHECK_FLAG, "1")
    apiClient
      .get<{ all_agreed: boolean; reauthorize_url: string | null }>(
        "/api/kakao/me/scopes"
      )
      .then(({ data }) => {
        if (!data.all_agreed && data.reauthorize_url) {
          window.location.href = data.reauthorize_url
        }
      })
      .catch((err) => console.error("카카오 scope 체크 실패:", err))
  }, [user])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    )
  }

  if (!user) return null

  const visibleNav = NAV_ITEMS.filter((item) =>
    (item.roles as readonly string[]).includes(user.role)
  )

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 상단 네비게이션 */}
      <header className="border-b bg-white">
        <div className="mx-auto flex h-14 w-[90%] items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/buildings" className="text-lg font-bold">
              모니터링
            </Link>
            <nav className="flex gap-1">
              {visibleNav.map((item) => (
                <Link key={item.href} href={item.href}>
                  <Button
                    variant={pathname === item.href ? "secondary" : "ghost"}
                    size="sm"
                  >
                    {item.label}
                  </Button>
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm">{user.name}</span>
            <Badge variant="outline">{ROLE_LABELS[user.role]}</Badge>
            <Separator orientation="vertical" className="h-5" />
            <Button variant="ghost" size="sm" onClick={logout}>
              로그아웃
            </Button>
          </div>
        </div>
      </header>

      {/* 본문 */}
      <main className="mx-auto w-[90%] py-6">{children}</main>
    </div>
  )
}
