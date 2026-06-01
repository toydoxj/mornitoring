"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ClipboardCheck,
  MessageSquarePlus,
  RefreshCw,
  Search,
  Send,
  Trash2,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import {
  CHECKLIST_CATEGORIES,
  CHECKLIST_ITEMS,
  CHECKLIST_SOURCE,
  type ChecklistItem,
} from "@/lib/checklist-data"
import apiClient from "@/lib/api/client"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/stores/authStore"

interface ChecklistOpinion {
  id: number
  item_key: string
  author_id: number
  author_name: string
  content: string
  created_at: string
  updated_at: string
}

interface ChecklistOpinionSummary {
  item_key: string
  count: number
  latest_at: string | null
}

type ApiDetail = string | { message?: string } | { msg?: string }[]

interface ApiError {
  response?: {
    data?: {
      detail?: ApiDetail
    }
  }
}

function getErrorMessage(error: unknown, fallback: string) {
  const detail = (error as ApiError).response?.data?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg ?? "입력값을 확인해주세요").join("\n")
  }
  if (detail?.message) return detail.message
  return fallback
}

function formatDateTime(value: string | null) {
  if (!value) return "-"
  return new Date(value).toLocaleString("ko-KR")
}

function getSearchText(item: ChecklistItem) {
  return [
    item.category,
    item.section,
    item.code,
    item.title,
    item.standard,
    ...item.checks.flatMap((check) => [check.detail ?? "", check.action ?? ""]),
  ]
    .join(" ")
    .toLowerCase()
}

export default function ChecklistPage() {
  const user = useAuthStore((state) => state.user)
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("all")
  const [selectedKey, setSelectedKey] = useState(CHECKLIST_ITEMS[0]?.key ?? "")
  const [summaries, setSummaries] = useState<ChecklistOpinionSummary[]>([])
  const [opinions, setOpinions] = useState<ChecklistOpinion[]>([])
  const [isSummaryLoading, setIsSummaryLoading] = useState(false)
  const [isOpinionsLoading, setIsOpinionsLoading] = useState(false)
  const [draft, setDraft] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const summaryByItem = useMemo(() => {
    return new Map(summaries.map((summary) => [summary.item_key, summary]))
  }, [summaries])

  const totalOpinions = useMemo(() => {
    return summaries.reduce((sum, summary) => sum + summary.count, 0)
  }, [summaries])

  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return CHECKLIST_ITEMS.filter((item) => {
      const matchesCategory = category === "all" || item.category === category
      const matchesQuery =
        normalizedQuery.length === 0 || getSearchText(item).includes(normalizedQuery)
      return matchesCategory && matchesQuery
    })
  }, [category, query])

  const selectedItem = useMemo(() => {
    return (
      filteredItems.find((item) => item.key === selectedKey) ??
      filteredItems[0] ??
      CHECKLIST_ITEMS[0]
    )
  }, [filteredItems, selectedKey])

  const fetchSummaries = useCallback(async () => {
    setIsSummaryLoading(true)
    try {
      const { data } = await apiClient.get<ChecklistOpinionSummary[]>(
        "/api/checklist/opinions/summary"
      )
      setSummaries(data)
    } catch (err) {
      console.error("상세체크리스트 의견 요약 조회 실패:", err)
    } finally {
      setIsSummaryLoading(false)
    }
  }, [])

  const fetchOpinions = useCallback(async (itemKey: string) => {
    setIsOpinionsLoading(true)
    try {
      const { data } = await apiClient.get<ChecklistOpinion[]>(
        `/api/checklist/items/${encodeURIComponent(itemKey)}/opinions`
      )
      setOpinions(data)
    } catch (err) {
      console.error("상세체크리스트 의견 조회 실패:", err)
      setOpinions([])
    } finally {
      setIsOpinionsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSummaries()
  }, [fetchSummaries])

  useEffect(() => {
    if (filteredItems.length === 0) return
    if (!filteredItems.some((item) => item.key === selectedKey)) {
      setSelectedKey(filteredItems[0].key)
    }
  }, [filteredItems, selectedKey])

  useEffect(() => {
    if (selectedItem) {
      fetchOpinions(selectedItem.key)
    }
  }, [fetchOpinions, selectedItem])

  const handleSubmitOpinion = async () => {
    if (!selectedItem || !draft.trim()) return
    setIsSubmitting(true)
    try {
      await apiClient.post(
        `/api/checklist/items/${encodeURIComponent(selectedItem.key)}/opinions`,
        { content: draft }
      )
      setDraft("")
      await Promise.all([fetchSummaries(), fetchOpinions(selectedItem.key)])
    } catch (err) {
      alert(getErrorMessage(err, "의견 등록에 실패했습니다"))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteOpinion = async (opinionId: number) => {
    if (!selectedItem) return
    if (!confirm("의견을 삭제하시겠습니까?")) return

    setDeletingId(opinionId)
    try {
      await apiClient.delete(`/api/checklist/opinions/${opinionId}`)
      await Promise.all([fetchSummaries(), fetchOpinions(selectedItem.key)])
    } catch (err) {
      alert(getErrorMessage(err, "의견 삭제에 실패했습니다"))
    } finally {
      setDeletingId(null)
    }
  }

  const selectedSummary = selectedItem ? summaryByItem.get(selectedItem.key) : undefined
  const canModerate = user && ["team_leader", "chief_secretary"].includes(user.role)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold">상세체크리스트</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {CHECKLIST_SOURCE.fileName} · {CHECKLIST_SOURCE.sheetName}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary">항목 {CHECKLIST_SOURCE.itemCount}개</Badge>
          <Badge variant="outline">의견 {totalOpinions}건</Badge>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="space-y-3">
          <div className="rounded-md border bg-white p-3">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px]">
              <div className="space-y-2">
                <Label htmlFor="checklist-search">검색</Label>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="checklist-search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    className="pl-9"
                    placeholder="번호, 항목, 기준, 확인사항"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="checklist-category">구분</Label>
                <select
                  id="checklist-category"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  className="h-8 w-full rounded-md border bg-background px-3 text-sm"
                >
                  <option value="all">전체 구분</option>
                  {CHECKLIST_CATEGORIES.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="rounded-md border bg-white">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <p className="text-sm font-medium">항목 목록</p>
              <span className="text-xs text-muted-foreground">
                {filteredItems.length.toLocaleString("ko-KR")}개 표시
              </span>
            </div>
            <div className="max-h-[calc(100vh-260px)] overflow-y-auto">
              {filteredItems.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  검색 조건에 맞는 항목이 없습니다
                </div>
              ) : (
                filteredItems.map((item) => {
                  const summary = summaryByItem.get(item.key)
                  const isSelected = selectedItem?.key === item.key
                  return (
                    <button
                      key={item.key}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setSelectedKey(item.key)}
                      className={cn(
                        "block w-full border-b px-3 py-3 text-left transition-colors last:border-b-0 hover:bg-muted/50",
                        isSelected && "bg-primary/5"
                      )}
                    >
                      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={isSelected ? "default" : "secondary"}>
                              {item.code}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {item.category} · {item.section}
                            </span>
                          </div>
                          <p className="break-words text-sm font-medium">{item.title}</p>
                          <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                            {item.standard}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                          <span>확인 {item.checks.length}개</span>
                          <Badge variant={summary ? "outline" : "secondary"}>
                            의견 {summary?.count ?? 0}
                          </Badge>
                        </div>
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </div>
        </section>

        <aside className="space-y-3 xl:sticky xl:top-20 xl:self-start">
          <div className="rounded-md border bg-white p-4">
            {selectedItem ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{selectedItem.code}</Badge>
                    <Badge variant="outline">{selectedItem.section}</Badge>
                  </div>
                  <h2 className="break-words text-lg font-bold">{selectedItem.title}</h2>
                  <p className="text-xs text-muted-foreground">{selectedItem.category}</p>
                  <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-xs">
                    {selectedItem.standard}
                  </p>
                </div>

                <Separator />

                <div className="space-y-2">
                  <p className="text-sm font-semibold">상세 내용</p>
                  {selectedItem.checks.length === 0 ? (
                    <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
                      등록된 세부 확인사항이 없습니다
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {selectedItem.checks.map((check, index) => (
                        <div key={`${selectedItem.key}-${index}`} className="rounded-md border p-3">
                          <p className="whitespace-pre-wrap break-words text-sm font-medium">
                            {check.detail ?? "상세 내용 없음"}
                          </p>
                          {check.action && (
                            <p className="mt-2 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                              {check.action}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">선택된 항목이 없습니다</p>
            )}
          </div>

          <div className="rounded-md border bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <MessageSquarePlus className="h-5 w-5 text-primary" />
                  <h2 className="text-lg font-bold">항목 의견</h2>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {selectedSummary
                    ? `최근 의견 ${formatDateTime(selectedSummary.latest_at)}`
                    : "아직 의견이 없습니다"}
                </p>
              </div>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => selectedItem && fetchOpinions(selectedItem.key)}
                disabled={isOpinionsLoading || isSummaryLoading}
                aria-label="의견 새로고침"
              >
                <RefreshCw
                  className={cn((isOpinionsLoading || isSummaryLoading) && "animate-spin")}
                />
              </Button>
            </div>

            <div className="mt-4 space-y-2">
              <Label htmlFor="checklist-opinion">의견</Label>
              <textarea
                id="checklist-opinion"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="min-h-[110px] w-full rounded-md border px-3 py-2 text-sm"
                maxLength={2000}
                placeholder="검토기준 보완, 표현 수정, 사례 추가 의견"
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  {draft.length.toLocaleString("ko-KR")} / 2,000
                </span>
                <Button
                  onClick={handleSubmitOpinion}
                  disabled={!selectedItem || !draft.trim()}
                  loading={isSubmitting}
                  loadingText="등록 중..."
                >
                  <Send />
                  등록
                </Button>
              </div>
            </div>

            <Separator className="my-4" />

            <div className="space-y-2">
              {isOpinionsLoading ? (
                <p className="py-8 text-center text-sm text-muted-foreground">로딩 중...</p>
              ) : opinions.length === 0 ? (
                <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
                  등록된 의견이 없습니다
                </p>
              ) : (
                opinions.map((opinion) => {
                  const canDelete = user?.id === opinion.author_id || !!canModerate
                  return (
                    <div key={opinion.id} className="rounded-md border p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {opinion.author_name}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatDateTime(opinion.created_at)}
                          </p>
                        </div>
                        {canDelete && (
                          <Button
                            size="icon-xs"
                            variant="ghost"
                            onClick={() => handleDeleteOpinion(opinion.id)}
                            disabled={deletingId === opinion.id}
                            aria-label="의견 삭제"
                          >
                            <Trash2
                              className={cn(deletingId === opinion.id && "animate-pulse")}
                            />
                          </Button>
                        )}
                      </div>
                      <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                        {opinion.content}
                      </p>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
