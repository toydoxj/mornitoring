"use client"

import { useEffect } from "react"
import { useRouter, usePathname } from "next/navigation"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { useAuthStore } from "@/stores/authStore"
import { ROLE_LABELS } from "@/types"

const NAV_ITEMS = [
  { href: "/dashboard", label: "대시보드", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/buildings", label: "통합관리대장", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/my-reviews", label: "내 검토 대상", roles: ["reviewer"] },
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
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
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
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  )
}
