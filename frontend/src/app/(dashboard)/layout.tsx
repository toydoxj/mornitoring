"use client"

import { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import Link from "next/link"
import Image from "next/image"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { useAuthStore } from "@/stores/authStore"
import { ROLE_LABELS } from "@/types"
import apiClient from "@/lib/api/client"

const NAV_ITEMS = [
  { href: "/dashboard", label: "대시보드", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/announcements", label: "공지사항", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/discussions", label: "토론방", roles: ["team_leader", "chief_secretary", "secretary", "reviewer"] },
  { href: "/buildings", label: "통합관리대장", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/distribution", label: "도서접수/배포", roles: ["team_leader", "chief_secretary"] },
  { href: "/my-reviews", label: "내 검토 대상", roles: ["chief_secretary", "secretary", "reviewer"] },
  { href: "/review-files", label: "검토서 관리", roles: ["team_leader", "chief_secretary"] },
  { href: "/inquiries", label: "문의사항", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/inappropriate-review", label: "부적합 검토", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/statistics", label: "통계자료", roles: ["team_leader", "chief_secretary", "secretary"] },
  { href: "/reminders", label: "리마인드", roles: ["team_leader", "chief_secretary", "secretary"] },
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

  // 카카오 안내 배너 dismiss 상태 (sessionStorage 1회 lazy init)
  const [bannerDismissed, setBannerDismissed] = useState<{
    notLinked: boolean
    insufficient: boolean
  }>(() => {
    if (typeof window === "undefined") return { notLinked: false, insufficient: false }
    return {
      notLinked: !!sessionStorage.getItem("kakao_banner_not_linked_dismissed"),
      insufficient: !!sessionStorage.getItem("kakao_banner_insufficient_dismissed"),
    }
  })

  const dismissBanner = (key: "notLinked" | "insufficient") => {
    const storageKey =
      key === "notLinked"
        ? "kakao_banner_not_linked_dismissed"
        : "kakao_banner_insufficient_dismissed"
    sessionStorage.setItem(storageKey, "1")
    setBannerDismissed((prev) => ({ ...prev, [key]: true }))
  }

  const handleConnectKakao = async () => {
    try {
      const { data } = await apiClient.get<{ url: string }>("/api/auth/kakao/login")
      window.location.href = data.url
    } catch (err) {
      console.error("카카오 연동 시작 실패:", err)
      alert("카카오 연동 시작에 실패했습니다. 잠시 후 다시 시도해주세요.")
    }
  }

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
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-lg font-bold"
            >
              <Image
                src="/ksea.png"
                alt="KSEA 로고"
                width={28}
                height={28}
                priority
                className="h-7 w-7 rounded"
              />
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

      {/* 카카오 연동 안내 배너 */}
      {!user.kakao_linked && !bannerDismissed.notLinked && (
        <div className="border-b border-amber-200 bg-amber-50 text-amber-900">
          <div className="mx-auto flex w-[90%] items-center justify-between gap-3 py-2 text-sm">
            <span>
              📱 카카오 알림을 받으려면 <strong>카카오 연동</strong>이 필요합니다.
              아래 버튼으로 카카오 로그인 + 동의를 진행해주세요.
            </span>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleConnectKakao}>
                카카오 연동하기
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => dismissBanner("notLinked")}
                className="text-amber-900"
              >
                닫기
              </Button>
            </div>
          </div>
        </div>
      )}
      {user.kakao_linked &&
        user.kakao_scopes_ok === false &&
        !bannerDismissed.insufficient && (
          <div className="border-b border-red-200 bg-red-50 text-red-900">
            <div className="mx-auto flex w-[90%] items-center justify-between gap-3 py-2 text-sm">
              <span>
                ⚠️ 카카오 알림을 받으려면 <strong>추가 동의</strong>가 필요합니다.
              </span>
              <div className="flex gap-2">
                {user.kakao_reauthorize_url && (
                  <Button
                    size="sm"
                    onClick={() => {
                      window.location.href = user.kakao_reauthorize_url!
                    }}
                  >
                    동의하러 가기
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => dismissBanner("insufficient")}
                  className="text-red-900"
                >
                  닫기
                </Button>
              </div>
            </div>
          </div>
        )}

      {/* 본문 */}
      <main className="mx-auto w-[90%] py-6">{children}</main>
    </div>
  )
}
