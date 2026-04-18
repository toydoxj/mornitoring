"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import { useAuthStore } from "@/stores/authStore"
import { PHASE_LABELS } from "@/types"

interface ReviewerStat {
  name: string
  total: number
  total_area: number
  area_over_1000: number
  high_risk: number
  doc_received: number
  submitted: number
  not_submitted: number
  completed: number
}

interface DashboardStats {
  total: number
  // 전체 흐름 요약 (서로 겹치지 않음)
  unassigned: number
  assigned: number
  docs_waiting_review: number
  review_in_progress: number
  completed: number
  // 기존 호환
  doc_received: number
  not_submitted: number
  preliminary: number
  supplement: number
  phase_counts: Record<string, number>
  reviewer_stats: ReviewerStat[]
}

interface MyStats {
  total: number
  total_area: number
  area_over_1000: number
  high_risk: number
  need_review: number
  submitted: number
  submitted_preliminary: number
  submitted_supplement: number
  elapsed_buckets: Record<string, number>
  final_counts: {
    pass: number
    pass_supplement: number
    fail: number
    excluded: number
  }
}

const ELAPSED_ORDER = ["1일", "2일", "3일", "4일", "5일", "6일", "7일", "1주", "2주이상"] as const

interface PostItem {
  id: number
  author_name: string
  title: string
  created_at: string
  comment_count: number
}

interface NotificationItem {
  id: number
  template_type: string
  title: string
  message: string | null
  is_sent: boolean
  sent_at: string | null
  created_at: string
  error_message: string | null
}

interface MyInquiryItem {
  id: number
  building_id: number
  mgmt_no: string
  content: string
  reply: string | null
  status: string
  created_at: string
}

const INQUIRY_STATUS_LABELS: Record<string, string> = {
  open: "접수",
  asking_agency: "관리원문의중",
  completed: "완료",
}

const TEMPLATE_LABELS: Record<string, string> = {
  doc_received: "도서 접수",
  review_request: "검토 요청",
  reminder: "리마인더",
}

export default function DashboardPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [myStats, setMyStats] = useState<MyStats | null>(null)
  const [announcements, setAnnouncements] = useState<PostItem[]>([])
  const [discussions, setDiscussions] = useState<PostItem[]>([])
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [myInquiries, setMyInquiries] = useState<MyInquiryItem[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const isAdmin = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const { data: mine } = await apiClient.get<MyStats>("/api/buildings/my-stats")
        setMyStats(mine)
      } catch (err) {
        console.error("개인 통계 조회 실패:", err)
      }

      // 공지사항 최신 5건
      try {
        const { data } = await apiClient.get<{ items: PostItem[] }>(
          "/api/announcements",
          { params: { size: 5 } }
        )
        setAnnouncements(data.items)
      } catch (err) {
        console.error("공지사항 조회 실패:", err)
      }

      // 토론방 최신 5건
      try {
        const { data } = await apiClient.get<{ items: PostItem[] }>(
          "/api/discussions",
          { params: { size: 5 } }
        )
        setDiscussions(data.items)
      } catch (err) {
        console.error("토론방 조회 실패:", err)
      }

      // 내가 받은 카톡 알림 최신 5건 (모든 로그인 사용자)
      try {
        const { data } = await apiClient.get<{ items: NotificationItem[] }>(
          "/api/notifications/my",
          { params: { size: 5, page: 1 } }
        )
        setNotifications(data.items)
      } catch (err) {
        console.error("내 알림 조회 실패:", err)
      }

      // 나의 문의사항 최신 5건
      try {
        const { data } = await apiClient.get<{ items: MyInquiryItem[] }>(
          "/api/reviews/my-inquiries",
          { params: { size: 5 } }
        )
        setMyInquiries(data.items)
      } catch (err) {
        console.error("내 문의사항 조회 실패:", err)
      }

      // 간사 이상만 전체 통계
      if (isAdmin) {
        try {
          const { data } = await apiClient.get<DashboardStats>("/api/buildings/stats")
          setStats(data)
        } catch (err) {
          console.error("전체 통계 조회 실패:", err)
        }
      }
      setIsLoading(false)
    }
    fetchAll()
  }, [isAdmin])

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

      {/* 내 담당 현황 (상단, 버킷 스타일) */}
      {myStats && myStats.total > 0 && (
        <section className="rounded-2xl border bg-gradient-to-br from-slate-50 to-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <span className="inline-block h-5 w-1 rounded-full bg-indigo-500" />
            <h2 className="text-lg font-bold">내 담당 현황</h2>
            <span className="text-xs text-muted-foreground">배정된 건물 기준</span>
          </div>

          <div className="space-y-4">
            {/* 1행: 진행 지표 4카드 */}
            <div className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
              <Bucket label="배정" value={myStats.total} tint="indigo" suffix="건" />
              <Bucket label="검토서 미제출" value={myStats.need_review} tint="red" suffix="건" />
              <SubmittedBucket
                preliminary={myStats.submitted_preliminary}
                supplement={myStats.submitted_supplement}
              />
              <FinalBucket counts={myStats.final_counts} />
            </div>

            {/* 구분선 */}
            <div className="border-t border-slate-200" />

            {/* 2행: 접수 후 경과일수 9버킷 */}
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">
                접수 후 경과일수 <span className="text-xs text-muted-foreground">(검토서 미제출 건)</span>
              </p>
              <div className="grid gap-2 grid-cols-3 md:grid-cols-5 lg:grid-cols-9">
                {ELAPSED_ORDER.map((key) => {
                  const count = myStats.elapsed_buckets[key] ?? 0
                  const isLong = key === "1주" || key === "2주이상"
                  const tint: BucketTint = isLong
                    ? "red"
                    : count > 0
                      ? "amber"
                      : "slate"
                  return <Bucket key={key} label={key} value={count} tint={tint} compact />
                })}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* 상단 위젯 — 공지사항 / 카톡 알림 / 토론방 / 나의 문의사항 */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* 공지사항 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-base">공지사항</CardTitle>
            <button
              className="text-xs text-primary hover:underline"
              onClick={() => router.push("/announcements")}
            >
              전체 보기 →
            </button>
          </CardHeader>
          <CardContent className="space-y-2">
            {announcements.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">등록된 공지가 없습니다.</p>
            ) : (
              announcements.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-2 rounded-md border p-2 cursor-pointer hover:bg-muted/30"
                  onClick={() => router.push(`/announcements/${a.id}`)}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{a.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {a.author_name} · {new Date(a.created_at).toLocaleDateString("ko-KR")}
                    </p>
                  </div>
                  {a.comment_count > 0 && (
                    <Badge variant="secondary" className="text-xs shrink-0">
                      💬 {a.comment_count}
                    </Badge>
                  )}
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* 내가 받은 카톡 알림 */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">내가 받은 카톡 알림</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {notifications.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">받은 알림이 없습니다.</p>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className="rounded-md border p-2"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs shrink-0">
                      {TEMPLATE_LABELS[n.template_type] ?? n.template_type}
                    </Badge>
                    <p className="truncate text-sm font-medium">{n.title}</p>
                  </div>
                  {n.message && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2 whitespace-pre-wrap break-words">
                      {n.message}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    {new Date(n.sent_at ?? n.created_at).toLocaleString("ko-KR")}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* 토론방 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-base">토론방</CardTitle>
            <button
              className="text-xs text-primary hover:underline"
              onClick={() => router.push("/discussions")}
            >
              전체 보기 →
            </button>
          </CardHeader>
          <CardContent className="space-y-2">
            {discussions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">등록된 글이 없습니다.</p>
            ) : (
              discussions.map((d) => (
                <div
                  key={d.id}
                  className="flex items-center justify-between gap-2 rounded-md border p-2 cursor-pointer hover:bg-muted/30"
                  onClick={() => router.push(`/discussions/${d.id}`)}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{d.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {d.author_name} · {new Date(d.created_at).toLocaleDateString("ko-KR")}
                    </p>
                  </div>
                  {d.comment_count > 0 && (
                    <Badge variant="secondary" className="text-xs shrink-0">
                      💬 {d.comment_count}
                    </Badge>
                  )}
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* 나의 문의사항 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-base">나의 문의사항</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {myInquiries.length === 0 ? (
              <p className="text-sm text-muted-foreground py-2">작성한 문의가 없습니다.</p>
            ) : (
              myInquiries.map((q) => (
                <div
                  key={q.id}
                  className="rounded-md border p-2 cursor-pointer hover:bg-muted/30"
                  onClick={() =>
                    router.push(`/buildings/${q.building_id}`)
                  }
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={q.status === "completed" ? "default" : "outline"}
                      className="text-xs shrink-0"
                    >
                      {INQUIRY_STATUS_LABELS[q.status] ?? q.status}
                    </Badge>
                    <p className="truncate text-sm font-medium font-mono">{q.mgmt_no}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground line-clamp-2 whitespace-pre-wrap break-words">
                    {q.content}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {new Date(q.created_at).toLocaleDateString("ko-KR")}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>


      {/* 전체 통계 (간사 이상) */}
      {isAdmin && stats && (
        <>
          <div>
            <h2 className="text-lg font-bold mb-2">전체 현황</h2>
            <p className="text-xs text-muted-foreground mb-2">
              각 카드는 서로 겹치지 않는 단계군입니다 (합 = 총 등록건).
            </p>
            <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
              <StatCard title="총 등록건" value={stats.total} />
              <StatCard title="미배정" value={stats.unassigned} color="red" />
              <StatCard title="배정 완료" value={stats.assigned} />
              <StatCard title="검토서 대기" value={stats.docs_waiting_review} color="blue" />
              <StatCard title="검토 진행중" value={stats.review_in_progress} />
              <StatCard title="최종 완료" value={stats.completed} color="green" />
            </div>
          </div>

          {/* 단계별 현황 */}
          <Card>
            <CardHeader>
              <CardTitle>단계별 현황</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(PHASE_LABELS).map(([key, label]) => {
                  const count = stats.phase_counts[key] || 0
                  if (count === 0 && !["doc_received", "preliminary", "none"].includes(key)) return null
                  return (
                    <div key={key} className="flex items-center justify-between rounded-md border p-3">
                      <span className="text-sm">{label}</span>
                      <span className="text-lg font-bold">{count}</span>
                    </div>
                  )
                })}
                <div className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm">미접수</span>
                  <span className="text-lg font-bold">{stats.phase_counts["none"] || 0}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* 위원별 현황 */}
      {isAdmin && stats && stats.reviewer_stats.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>검토위원별 현황</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border max-h-[500px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>검토위원</TableHead>
                    <TableHead className="w-[70px] text-center">배정</TableHead>
                    <TableHead className="w-[100px] text-right">연면적합</TableHead>
                    <TableHead className="w-[70px] text-center">1000↑</TableHead>
                    <TableHead className="w-[70px] text-center">고위험</TableHead>
                    <TableHead className="w-[70px] text-center">배포</TableHead>
                    <TableHead className="w-[70px] text-center">제출</TableHead>
                    <TableHead className="w-[70px] text-center">미제출</TableHead>
                    <TableHead className="w-[70px] text-center">완료</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.reviewer_stats.map((r) => (
                    <TableRow key={r.name}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell className="text-center">{r.total}</TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {r.total_area.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.area_over_1000 > 0 ? (
                          <Badge variant="secondary">{r.area_over_1000}</Badge>
                        ) : "0"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.high_risk > 0 ? (
                          <Badge variant="destructive">{r.high_risk}</Badge>
                        ) : "0"}
                      </TableCell>
                      <TableCell className="text-center">{r.doc_received}</TableCell>
                      <TableCell className="text-center">
                        {r.submitted > 0 ? (
                          <Badge variant="default">{r.submitted}</Badge>
                        ) : (
                          "0"
                        )}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.not_submitted > 0 ? (
                          <Badge variant="destructive">{r.not_submitted}</Badge>
                        ) : (
                          "0"
                        )}
                      </TableCell>
                      <TableCell className="text-center">{r.completed}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

type BucketTint = "indigo" | "red" | "green" | "blue" | "orange" | "slate" | "amber"

const BUCKET_VALUE_COLOR: Record<BucketTint, string> = {
  indigo: "text-indigo-600",
  red: "text-red-600",
  green: "text-emerald-600",
  blue: "text-blue-600",
  orange: "text-orange-600",
  slate: "text-slate-800",
  amber: "text-amber-600",
}

const BUCKET_ACCENT: Record<BucketTint, string> = {
  indigo: "before:bg-indigo-500",
  red: "before:bg-red-500",
  green: "before:bg-emerald-500",
  blue: "before:bg-blue-500",
  orange: "before:bg-orange-500",
  slate: "before:bg-slate-400",
  amber: "before:bg-amber-500",
}

function SubmittedBucket({
  preliminary,
  supplement,
}: {
  preliminary: number
  supplement: number
}) {
  const total = preliminary + supplement
  return (
    <div className="relative overflow-hidden rounded-xl border bg-white p-4 transition-all hover:shadow-md before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-emerald-500">
      <p className="text-xs font-medium text-muted-foreground">제출 검토서</p>
      <div className="mt-2 flex items-baseline gap-1">
        <p className="text-3xl font-bold tracking-tight text-emerald-600">
          {total.toLocaleString()}
        </p>
        <span className="text-sm text-muted-foreground">건</span>
      </div>
      <div className="mt-2 flex gap-3 text-xs text-muted-foreground">
        <span>예비 <strong className="text-slate-700">{preliminary}</strong></span>
        <span>보완 <strong className="text-slate-700">{supplement}</strong></span>
      </div>
    </div>
  )
}

function FinalBucket({
  counts,
}: {
  counts: { pass: number; pass_supplement: number; fail: number; excluded: number }
}) {
  const total = counts.pass + counts.pass_supplement + counts.fail + counts.excluded
  return (
    <div className="relative overflow-hidden rounded-xl border bg-white p-4 transition-all hover:shadow-md before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:bg-violet-500">
      <p className="text-xs font-medium text-muted-foreground">최종 완료</p>
      <div className="mt-2 flex items-baseline gap-1">
        <p className="text-3xl font-bold tracking-tight text-violet-600">
          {total.toLocaleString()}
        </p>
        <span className="text-sm text-muted-foreground">건</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        <span>적합 <strong className="text-emerald-700">{counts.pass}</strong></span>
        <span>보완적합 <strong className="text-blue-700">{counts.pass_supplement}</strong></span>
        <span>부적합 <strong className="text-red-700">{counts.fail}</strong></span>
        <span>대상제외 <strong className="text-slate-700">{counts.excluded}</strong></span>
      </div>
    </div>
  )
}

function Bucket({
  label,
  value,
  tint = "slate",
  suffix,
  suffixSmall,
  compact,
}: {
  label: string
  value: number | string
  tint?: BucketTint
  suffix?: string
  suffixSmall?: boolean
  compact?: boolean
}) {
  if (compact) {
    return (
      <div className="rounded-lg border bg-white p-2 text-center transition-all hover:border-slate-300 hover:shadow-sm">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <p className={`mt-0.5 text-xl font-bold ${BUCKET_VALUE_COLOR[tint]}`}>
          {typeof value === "number" ? value.toLocaleString() : value}
        </p>
      </div>
    )
  }

  return (
    <div
      className={`
        relative overflow-hidden rounded-xl border bg-white p-4 transition-all hover:shadow-md
        before:absolute before:left-0 before:top-0 before:h-full before:w-1 ${BUCKET_ACCENT[tint]}
      `}
    >
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-2 flex items-baseline gap-1 flex-wrap">
        <p className={`text-3xl font-bold tracking-tight ${BUCKET_VALUE_COLOR[tint]}`}>
          {typeof value === "number" ? value.toLocaleString() : value}
        </p>
        {suffix && (
          <span className={`${suffixSmall ? "text-[11px]" : "text-sm"} text-muted-foreground`}>
            {suffix}
          </span>
        )}
      </div>
    </div>
  )
}

function StatCard({
  title,
  value,
  color,
  suffix,
}: {
  title: string
  value: number
  color?: "blue" | "red" | "green"
  suffix?: string
}) {
  const colorClass = color === "blue"
    ? "text-blue-600"
    : color === "red"
    ? "text-red-600"
    : color === "green"
    ? "text-green-600"
    : ""

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-3xl font-bold ${colorClass}`}>
          {value.toLocaleString()}
          {suffix && <span className="ml-1 text-base font-normal text-muted-foreground">{suffix}</span>}
        </p>
      </CardContent>
    </Card>
  )
}
