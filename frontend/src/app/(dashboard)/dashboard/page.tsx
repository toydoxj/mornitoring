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

interface FinalCounts {
  pass: number
  pass_supplement: number
  fail: number
  fail_no_response: number
  excluded: number
}

interface InquiryCounts {
  open: number
  asking_agency: number
  completed: number
}

interface DashboardStats {
  total: number
  // 전체 흐름 요약
  unassigned: number
  assigned: number
  docs_waiting_review: number
  docs_waiting_review_preliminary: number
  docs_waiting_review_supplement: number
  review_in_progress: number
  review_in_progress_preliminary: number
  review_in_progress_supplement: number
  uploaded_reports_preliminary: number
  uploaded_reports_supplement: number
  completed: number
  final_counts: FinalCounts
  inquiry_counts: InquiryCounts
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
  final_counts: FinalCounts
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

interface ReviewerSchedule {
  reviewer_user_id: number
  reviewer_name: string
  kakao_matched: boolean
  in_progress: number
  d_minus_3: number
  d_minus_2: number
  d_minus_1: number
  d_day: number
  overdue: number
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
  const [reviewerSchedule, setReviewerSchedule] = useState<ReviewerSchedule[]>([])
  const [isLoading, setIsLoading] = useState(true)
  // 병렬 호출 진행률 표시용
  const [loadedCount, setLoadedCount] = useState(0)
  const [totalTasks, setTotalTasks] = useState(0)

  const isAdmin = user && ["team_leader", "chief_secretary", "secretary"].includes(user.role)
  // 검토서 관리 페이지 이동 권한: 팀장/총괄간사만 (간사는 카드 비클릭)
  const canManageReports = !!user && ["team_leader", "chief_secretary"].includes(user.role)

  useEffect(() => {
    // 각 섹션은 독립적이므로 병렬 호출 + 개별 에러 격리로 첫 페인트 속도를 크게 줄인다.
    // 각 요청 완료 시 loadedCount를 증가시켜 사용자에게 진행률을 시각적으로 보여준다.
    const fetchAll = async () => {
      const trackProgress = <T,>(p: Promise<T>): Promise<T> => {
        return p.finally(() => setLoadedCount((c) => c + 1))
      }

      const tasks: Promise<void>[] = [
        trackProgress(apiClient.get<MyStats>("/api/buildings/my-stats"))
          .then(({ data }) => setMyStats(data))
          .catch((err) => console.error("개인 통계 조회 실패:", err)),

        trackProgress(apiClient.get<{ items: PostItem[] }>("/api/announcements", { params: { size: 5 } }))
          .then(({ data }) => setAnnouncements(data.items))
          .catch((err) => console.error("공지사항 조회 실패:", err)),

        trackProgress(apiClient.get<{ items: PostItem[] }>("/api/discussions", { params: { size: 5 } }))
          .then(({ data }) => setDiscussions(data.items))
          .catch((err) => console.error("토론방 조회 실패:", err)),

        trackProgress(apiClient.get<{ items: NotificationItem[] }>("/api/notifications/my", { params: { size: 5, page: 1 } }))
          .then(({ data }) => setNotifications(data.items))
          .catch((err) => console.error("내 알림 조회 실패:", err)),

        trackProgress(apiClient.get<{ items: MyInquiryItem[] }>("/api/reviews/my-inquiries", { params: { size: 5 } }))
          .then(({ data }) => setMyInquiries(data.items))
          .catch((err) => console.error("내 문의사항 조회 실패:", err)),
      ]

      if (isAdmin) {
        tasks.push(
          trackProgress(apiClient.get<DashboardStats>("/api/buildings/stats"))
            .then(({ data }) => setStats(data))
            .catch((err) => console.error("전체 통계 조회 실패:", err))
        )
        tasks.push(
          trackProgress(apiClient.get<ReviewerSchedule[]>("/api/buildings/reviewer-schedule"))
            .then(({ data }) => setReviewerSchedule(data))
            .catch((err) => console.error("검토위원 일정 조회 실패:", err))
        )
      }

      setTotalTasks(tasks.length)
      setLoadedCount(0)
      await Promise.all(tasks)
      setIsLoading(false)
    }
    fetchAll()
  }, [isAdmin])

  if (isLoading) {
    const percent = totalTasks > 0
      ? Math.min(100, Math.round((loadedCount / totalTasks) * 100))
      : 0
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20">
        <div className="text-sm text-muted-foreground">
          대시보드 불러오는 중... ({loadedCount}/{totalTasks || "-"})
        </div>
        <div className="h-2 w-64 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-primary transition-all duration-300 ease-out"
            style={{ width: `${percent}%` }}
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">대시보드</h1>
        <p className="text-sm text-muted-foreground">
          {user?.name}님, 환영합니다
        </p>
      </div>

      {/* 단계별 집계 / 현황 — 한 줄 2박스 (xl 이상), 그 이하는 세로 */}
      {isAdmin && stats && (
        <div className="grid gap-4 xl:grid-cols-5 xl:items-stretch">
          <Card className="xl:col-span-3 h-full">
            <CardHeader>
              <CardTitle>단계별 집계</CardTitle>
            </CardHeader>
            <CardContent className="flex-1">
              <FlowStages stats={stats} />
            </CardContent>
          </Card>

          <Card className="xl:col-span-2 h-full">
            <CardHeader>
              <CardTitle>현황</CardTitle>
            </CardHeader>
            <CardContent className="flex-1">
              <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-3">
                <BreakdownCard
                  title="검토서 미접수"
                  total={stats.docs_waiting_review_preliminary + stats.docs_waiting_review_supplement}
                  accent="blue"
                  items={[
                    { label: "예비", value: stats.docs_waiting_review_preliminary },
                    { label: "보완", value: stats.docs_waiting_review_supplement },
                  ]}
                />
                <BreakdownCard
                  title="업로드된 검토서"
                  total={stats.uploaded_reports_preliminary + stats.uploaded_reports_supplement}
                  accent="slate"
                  onClick={canManageReports ? () => router.push("/review-files") : undefined}
                  items={[
                    { label: "예비", value: stats.uploaded_reports_preliminary },
                    { label: "보완", value: stats.uploaded_reports_supplement },
                  ]}
                />
                <BreakdownCard
                  title="문의사항"
                  total={
                    stats.inquiry_counts.open +
                    stats.inquiry_counts.asking_agency +
                    stats.inquiry_counts.completed
                  }
                  accent="amber"
                  onClick={() => router.push("/inquiries")}
                  items={[
                    { label: "접수", value: stats.inquiry_counts.open },
                    { label: "관리원문의", value: stats.inquiry_counts.asking_agency },
                    { label: "완료", value: stats.inquiry_counts.completed },
                  ]}
                />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

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

      {/* 검토위원별 일정관리 (관리자 전용) */}
      {isAdmin && reviewerSchedule.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>검토위원별 일정관리</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              검토서 미제출 건을 오늘 기준으로 D-3 ~ 초과로 분류. 긴급도 높은 순.
            </p>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border max-h-[500px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>검토위원</TableHead>
                    <TableHead className="w-[90px] text-center">미제출</TableHead>
                    <TableHead className="w-[60px] text-center">D-3</TableHead>
                    <TableHead className="w-[60px] text-center">D-2</TableHead>
                    <TableHead className="w-[60px] text-center">D-1</TableHead>
                    <TableHead className="w-[70px] text-center">D-day</TableHead>
                    <TableHead className="w-[70px] text-center">초과</TableHead>
                    <TableHead className="w-[70px] text-center">카카오</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reviewerSchedule.map((r) => (
                    <TableRow key={r.reviewer_user_id}>
                      <TableCell className="font-medium">{r.reviewer_name}</TableCell>
                      <TableCell className="text-center">{r.in_progress}</TableCell>
                      <TableCell className="text-center">
                        {r.d_minus_3 > 0 ? r.d_minus_3 : "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.d_minus_2 > 0 ? r.d_minus_2 : "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.d_minus_1 > 0 ? (
                          <Badge variant="secondary">{r.d_minus_1}</Badge>
                        ) : "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.d_day > 0 ? (
                          <Badge variant="default">{r.d_day}</Badge>
                        ) : "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        {r.overdue > 0 ? (
                          <Badge variant="destructive">{r.overdue}</Badge>
                        ) : "-"}
                      </TableCell>
                      <TableCell className="text-center text-xs">
                        {r.kakao_matched ? "✓" : "✗"}
                      </TableCell>
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

function FinalBucket({ counts }: { counts: FinalCounts }) {
  const total =
    counts.pass + counts.pass_supplement + counts.fail + counts.fail_no_response + counts.excluded
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
        <span>부적합(미회신) <strong className="text-red-700">{counts.fail_no_response}</strong></span>
        <span>대상제외 <strong className="text-slate-700">{counts.excluded}</strong></span>
      </div>
    </div>
  )
}

type BreakdownAccent = "blue" | "slate" | "amber" | "green" | "violet" | "indigo"

const BREAKDOWN_BAR: Record<BreakdownAccent, string> = {
  blue: "before:bg-blue-500",
  slate: "before:bg-slate-500",
  amber: "before:bg-amber-500",
  green: "before:bg-emerald-500",
  violet: "before:bg-violet-500",
  indigo: "before:bg-indigo-500",
}

const BREAKDOWN_VALUE: Record<BreakdownAccent, string> = {
  blue: "text-blue-600",
  slate: "text-slate-700",
  amber: "text-amber-600",
  green: "text-emerald-600",
  violet: "text-violet-600",
  indigo: "text-indigo-600",
}

function BreakdownCard({
  title,
  total,
  items,
  accent = "slate",
  onClick,
}: {
  title: string
  total: number
  items: { label: string; value: number }[]
  accent?: BreakdownAccent
  onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (!onClick) return
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick()
        }
      }}
      className={`
        relative overflow-hidden rounded-xl border bg-white p-4 transition-all hover:shadow-md
        before:absolute before:left-0 before:top-0 before:h-full before:w-1 ${BREAKDOWN_BAR[accent]}
        ${onClick ? "cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/40" : ""}
      `}
    >
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <div className="mt-2 flex items-baseline gap-1">
        <p className={`text-3xl font-bold tracking-tight ${BREAKDOWN_VALUE[accent]}`}>
          {total.toLocaleString()}
        </p>
        <span className="text-sm text-muted-foreground">건</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {items.map((it) => (
          <span key={it.label}>
            {it.label} <strong className="text-slate-700">{it.value}</strong>
          </span>
        ))}
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

function FlowStages({ stats }: { stats: DashboardStats }) {
  const phaseCounts = stats.phase_counts

  const preliminaryReceived = phaseCounts["doc_received"] || 0
  const preliminarySubmitted = phaseCounts["preliminary"] || 0
  const preliminaryTotal = preliminaryReceived + preliminarySubmitted

  const supplementRows = [1, 2, 3].map((n) => ({
    nth: n,
    received: phaseCounts[`supplement_${n}_received`] || 0,
    submitted: phaseCounts[`supplement_${n}`] || 0,
  }))
  const supplementTotal = supplementRows.reduce(
    (acc, r) => acc + r.received + r.submitted,
    0,
  )

  const finalTotal =
    stats.final_counts.pass +
    stats.final_counts.pass_supplement +
    stats.final_counts.fail +
    stats.final_counts.fail_no_response +
    stats.final_counts.excluded

  return (
    <div className="flex flex-col items-stretch gap-3 lg:flex-row">
      <FlowStageCard title="총 등록건" total={stats.total} accent="indigo" items={[]} />
      {/* 총 등록건은 전체 요약. 진행 단계와 구분해 화살표 대신 세로선으로 분리 */}
      <div
        className="hidden self-stretch lg:block lg:border-l lg:border-slate-200 lg:mx-1"
        aria-hidden
      />
      <FlowStageCard
        title="예비검토"
        total={preliminaryTotal}
        accent="slate"
        items={[
          { label: "접수", value: preliminaryReceived },
          { label: "제출", value: preliminarySubmitted },
        ]}
      />
      <FlowArrow />
      <FlowStageCard
        title="보완검토"
        total={supplementTotal}
        accent="amber"
        items={supplementRows.flatMap((r) => [
          { label: `${r.nth}차 접수`, value: r.received },
          { label: `${r.nth}차 제출`, value: r.submitted },
        ])}
        itemCols={2}
      />
      <FlowArrow />
      <FlowStageCard
        title="최종 완료"
        total={finalTotal}
        accent="green"
        items={[
          { label: "적합", value: stats.final_counts.pass },
          { label: "보완적합", value: stats.final_counts.pass_supplement },
          { label: "부적합", value: stats.final_counts.fail },
          { label: "부적합(미회신)", value: stats.final_counts.fail_no_response },
          { label: "대상제외", value: stats.final_counts.excluded },
        ]}
      />
    </div>
  )
}

function FlowArrow() {
  return (
    <div className="flex items-center justify-center text-slate-400">
      <span className="text-2xl lg:rotate-0 rotate-90 select-none" aria-hidden>→</span>
    </div>
  )
}

function FlowStageCard({
  title,
  total,
  items,
  accent,
  itemCols = 1,
}: {
  title: string
  total: number
  items: { label: string; value: number }[]
  accent: BreakdownAccent
  itemCols?: 1 | 2
}) {
  return (
    <div
      className={`
        relative flex-1 overflow-hidden rounded-xl border bg-white p-4 transition-all hover:shadow-sm
        before:absolute before:left-0 before:top-0 before:h-full before:w-1 ${BREAKDOWN_BAR[accent]}
      `}
    >
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <div className="mt-2 flex items-baseline gap-1">
        <p className={`text-3xl font-bold tracking-tight ${BREAKDOWN_VALUE[accent]}`}>
          {total.toLocaleString()}
        </p>
        <span className="text-sm text-muted-foreground">건</span>
      </div>
      {items.length > 0 && (
        <div
          className={`mt-3 grid gap-x-3 gap-y-0.5 text-xs text-muted-foreground ${
            itemCols === 2 ? "grid-cols-2" : "grid-cols-1"
          }`}
        >
          {items.map((it) => (
            <div key={it.label} className="flex items-center justify-between">
              <span>{it.label}</span>
              <strong className="text-slate-700">{it.value}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

