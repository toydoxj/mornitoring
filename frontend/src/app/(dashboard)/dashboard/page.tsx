"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"
import type { BuildingListResponse } from "@/types"

interface DashboardStats {
  total: number
  preliminary: number
  supplement: number
  completed: number
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const [stats, setStats] = useState<DashboardStats>({
    total: 0,
    preliminary: 0,
    supplement: 0,
    completed: 0,
  })
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const fetchStats = async () => {
      try {
        // 전체 건수
        const { data: allData } = await apiClient.get<BuildingListResponse>(
          "/api/buildings",
          { params: { size: 1 } }
        )

        // 각 단계별 건수 (간단한 집계)
        const { data: prelimData } = await apiClient.get<BuildingListResponse>(
          "/api/buildings",
          { params: { phase: "preliminary", size: 1 } }
        )

        setStats({
          total: allData.total,
          preliminary: prelimData.total,
          supplement: Math.max(0, allData.total - prelimData.total),
          completed: 0,  // final_result가 있는 건수 (추후 API 확장)
        })
      } catch (err) {
        console.error("통계 조회 실패:", err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchStats()
  }, [])

  if (isLoading) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">대시보드</h1>
        <p className="text-sm text-muted-foreground">
          {user?.name}님, 환영합니다
        </p>
      </div>

      {/* 통계 카드 */}
      <div className="grid gap-4 md:grid-cols-4">
        <StatCard title="총 접수건" value={stats.total} />
        <StatCard title="예비검토" value={stats.preliminary} />
        <StatCard title="보완 진행" value={stats.supplement} />
        <StatCard title="완료" value={stats.completed} />
      </div>
    </div>
  )
}

function StatCard({ title, value }: { title: string; value: number }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-bold">{value.toLocaleString()}</p>
      </CardContent>
    </Card>
  )
}
