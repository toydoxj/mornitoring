"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { CheckCircle2, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import { cn } from "@/lib/utils"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

interface QualityCheckItem {
  building_id: number
  mgmt_no: string
  full_address: string | null
  building_name: string | null
  group_no: number | null
  reviewer_name: string | null
  quality_categories: string[]
  severity_levels: string[]
  detail_count: number
}

interface QualityCheckListResponse {
  items: QualityCheckItem[]
  total: number
}

interface QualityCheckResolveResponse {
  building_id: number
  updated_count: number
}

interface StructEngineerFirmBuilding {
  id: number
  mgmt_no: string
  building_name?: string | null
  struct_eng_name?: string | null
  reviewer_name?: string | null
  latest_reviewer_name?: string | null
  current_phase?: string | null
  final_result?: string | null
  latest_phase?: string | null
  latest_report_submitted_at?: string | null
}

interface StructEngineerFirmGroup {
  firm: string
  building_count: number
  reviewer_count: number
  submitted_count: number
  items: StructEngineerFirmBuilding[]
}

type ActiveTab = "qualityTargets" | "structEngineerFirms"

function formatList(values: string[]) {
  return values.length > 0 ? values.join(", ") : "-"
}

function formatText(value?: string | null) {
  const text = value?.trim()
  return text || "-"
}

function formatPhase(phase?: string | null) {
  if (!phase) return "-"
  return PHASE_LABELS[phase] ?? phase
}

function formatResult(result?: string | null) {
  if (!result) return "-"
  return RESULT_LABELS[result] ?? result
}

function formatLatestSubmission(item: StructEngineerFirmBuilding) {
  if (!item.latest_phase && !item.latest_report_submitted_at) return "-"
  const phaseLabel = formatPhase(item.latest_phase)
  if (!item.latest_report_submitted_at) return phaseLabel
  return `${phaseLabel} · ${item.latest_report_submitted_at}`
}

export default function QualityChecksPage() {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<ActiveTab>("qualityTargets")
  const [items, setItems] = useState<QualityCheckItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [resolveTarget, setResolveTarget] = useState<QualityCheckItem | null>(null)
  const [resolvingId, setResolvingId] = useState<number | null>(null)
  const [firmGroups, setFirmGroups] = useState<StructEngineerFirmGroup[]>([])
  const [selectedFirm, setSelectedFirm] = useState("")
  const [firmSearch, setFirmSearch] = useState("")
  const [isFirmLoading, setIsFirmLoading] = useState(true)

  const fetchItems = useCallback(async () => {
    setIsLoading(true)
    try {
      const { data } = await apiClient.get<QualityCheckListResponse>(
        "/api/reviews/quality-checks",
      )
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("검토서 확인 목록 조회 실패:", err)
      alert("검토서 확인 목록을 불러오지 못했습니다.")
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchStructEngineerFirms = useCallback(async () => {
    setIsFirmLoading(true)
    try {
      const { data } = await apiClient.get<StructEngineerFirmGroup[]>(
        "/api/reviews/struct-engineer-firms",
      )
      setFirmGroups(data)
      setSelectedFirm((current) => {
        if (current && data.some((group) => group.firm === current)) return current
        return data[0]?.firm ?? ""
      })
    } catch (err) {
      console.error("책임구조기술자 사무소 목록 조회 실패:", err)
      alert("책임구조기술자 사무소 목록을 불러오지 못했습니다.")
    } finally {
      setIsFirmLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  useEffect(() => {
    fetchStructEngineerFirms()
  }, [fetchStructEngineerFirms])

  const handleRefresh = () => {
    if (activeTab === "qualityTargets") {
      fetchItems()
      return
    }
    fetchStructEngineerFirms()
  }

  const handleConfirmSuitable = async () => {
    if (!resolveTarget) return
    setResolvingId(resolveTarget.building_id)
    try {
      await apiClient.patch<QualityCheckResolveResponse>(
        `/api/reviews/quality-checks/${resolveTarget.building_id}/suitable`,
      )
      setItems((current) =>
        current.filter((item) => item.building_id !== resolveTarget.building_id),
      )
      setTotal((current) => Math.max(0, current - 1))
      setResolveTarget(null)
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? "적합 처리에 실패했습니다."
      alert(msg)
    } finally {
      setResolvingId(null)
    }
  }

  const firmBuildingCount = firmGroups.reduce(
    (sum, group) => sum + group.building_count,
    0,
  )

  const filteredFirmGroups = useMemo(() => {
    const keyword = firmSearch.trim().toLowerCase()
    if (!keyword) return firmGroups
    return firmGroups.filter((group) => {
      if (group.firm.toLowerCase().includes(keyword)) return true
      return group.items.some((item) =>
        [
          item.mgmt_no,
          item.building_name,
          item.struct_eng_name,
          item.reviewer_name,
          item.latest_reviewer_name,
        ].some((value) => value?.toLowerCase().includes(keyword)),
      )
    })
  }, [firmGroups, firmSearch])

  const selectedFirmGroup = useMemo(() => {
    return (
      filteredFirmGroups.find((group) => group.firm === selectedFirm)
      ?? filteredFirmGroups[0]
      ?? null
    )
  }, [filteredFirmGroups, selectedFirm])

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold">검토서 확인</h1>
          <p className="text-sm text-muted-foreground">
            {activeTab === "qualityTargets"
              ? `심각도 L3/L4 또는 표현 품질 점검 대상 검토서 ${total.toLocaleString()}건`
              : `책임구조기술자 사무소 ${firmGroups.length.toLocaleString()}곳 · 관련 관리번호 ${firmBuildingCount.toLocaleString()}건`}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {activeTab === "structEngineerFirms" && (
            <Input
              className="w-full sm:w-80"
              placeholder="사무소, 관리번호, 검토자 검색"
              value={firmSearch}
              onChange={(e) => setFirmSearch(e.target.value)}
            />
          )}
          <Button
            type="button"
            variant="outline"
            onClick={handleRefresh}
            loading={activeTab === "qualityTargets" ? isLoading : isFirmLoading}
            loadingText="조회 중"
          >
            <RefreshCw />
            새로고침
          </Button>
        </div>
      </div>

      <div
        role="tablist"
        aria-label="검토서 확인 탭"
        className="inline-flex rounded-lg border bg-muted/30 p-1"
      >
        <Button
          type="button"
          role="tab"
          aria-selected={activeTab === "qualityTargets"}
          variant={activeTab === "qualityTargets" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("qualityTargets")}
        >
          확인 대상
        </Button>
        <Button
          type="button"
          role="tab"
          aria-selected={activeTab === "structEngineerFirms"}
          variant={activeTab === "structEngineerFirms" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("structEngineerFirms")}
        >
          책임구조기술자 사무소
        </Button>
      </div>

      {activeTab === "qualityTargets" ? (
        <div className="overflow-x-auto rounded-md border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[140px] text-center">관리번호</TableHead>
                <TableHead className="min-w-[260px]">주소</TableHead>
                <TableHead className="min-w-[180px]">건물명</TableHead>
                <TableHead className="w-[90px] text-center">조</TableHead>
                <TableHead className="w-[140px]">검토위원</TableHead>
                <TableHead className="min-w-[180px]">표현품질</TableHead>
                <TableHead className="w-[120px] text-center">심각도</TableHead>
                <TableHead className="w-[110px] text-center">적합</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                    불러오는 중...
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                    확인할 검토서가 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                items.map((item) => (
                  <TableRow key={item.building_id}>
                    <TableCell className="text-center">
                      <button
                        type="button"
                        className="font-mono font-medium text-blue-600 hover:underline"
                        onClick={() =>
                          router.push(`/buildings/${item.building_id}?from=quality-checks`)
                        }
                      >
                        {item.mgmt_no}
                      </button>
                    </TableCell>
                    <TableCell className="whitespace-normal break-words text-sm">
                      {item.full_address || "-"}
                    </TableCell>
                    <TableCell className="whitespace-normal break-words text-sm">
                      {item.building_name || "-"}
                    </TableCell>
                    <TableCell className="text-center">
                      {item.group_no ? `${item.group_no}조` : "-"}
                    </TableCell>
                    <TableCell className="font-medium">
                      {item.reviewer_name || "-"}
                      {item.detail_count > 1 && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          ({item.detail_count})
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-normal break-words text-sm">
                      {formatList(item.quality_categories)}
                    </TableCell>
                    <TableCell className="text-center text-sm">
                      {formatList(item.severity_levels)}
                    </TableCell>
                    <TableCell className="text-center">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                        loading={resolvingId === item.building_id}
                        loadingText="처리"
                        onClick={() => setResolveTarget(item)}
                      >
                        <CheckCircle2 />
                        적합
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      ) : isFirmLoading ? (
        <div className="py-20 text-center text-muted-foreground">불러오는 중...</div>
      ) : firmGroups.length === 0 ? (
        <div className="py-20 text-center text-muted-foreground">
          책임구조기술자 사무소 정보가 없습니다.
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,340px)_1fr]">
          <div className="overflow-hidden rounded-md border bg-white">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-sm font-medium">사무소 명단</span>
              <Badge variant="outline">{filteredFirmGroups.length.toLocaleString()}곳</Badge>
            </div>
            <div className="max-h-[640px] overflow-y-auto">
              {filteredFirmGroups.length === 0 ? (
                <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                  검색 결과가 없습니다.
                </div>
              ) : (
                filteredFirmGroups.map((group) => {
                  const isSelected = selectedFirmGroup?.firm === group.firm
                  return (
                    <button
                      key={group.firm}
                      type="button"
                      className={cn(
                        "flex w-full items-start justify-between gap-3 border-b px-3 py-3 text-left text-sm transition-colors last:border-b-0 hover:bg-muted/70",
                        isSelected && "bg-muted",
                      )}
                      onClick={() => setSelectedFirm(group.firm)}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{group.firm}</span>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          검토자 {group.reviewer_count.toLocaleString()}명 · 제출{" "}
                          {group.submitted_count.toLocaleString()}건
                        </span>
                      </span>
                      <Badge variant={isSelected ? "default" : "outline"}>
                        {group.building_count.toLocaleString()}건
                      </Badge>
                    </button>
                  )
                })
              )}
            </div>
          </div>

          <div className="space-y-3">
            {selectedFirmGroup ? (
              <>
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">{selectedFirmGroup.firm}</h2>
                    <p className="text-sm text-muted-foreground">
                      관련 관리번호 {selectedFirmGroup.building_count.toLocaleString()}건 · 검토자{" "}
                      {selectedFirmGroup.reviewer_count.toLocaleString()}명
                    </p>
                  </div>
                  <Badge variant="outline">
                    검토서 제출 {selectedFirmGroup.submitted_count.toLocaleString()}건
                  </Badge>
                </div>

                <div className="overflow-x-auto rounded-md border bg-white">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[140px]">관리번호</TableHead>
                        <TableHead>건축물명</TableHead>
                        <TableHead className="w-[140px]">책임구조기술자</TableHead>
                        <TableHead className="w-[120px]">검토자</TableHead>
                        <TableHead className="w-[190px]">최근 검토서</TableHead>
                        <TableHead className="w-[110px]">최종결과</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selectedFirmGroup.items.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>
                            <button
                              type="button"
                              className="font-mono text-sm font-medium text-blue-600 hover:underline"
                              onClick={() =>
                                router.push(`/buildings/${item.id}?from=quality-checks`)
                              }
                            >
                              {item.mgmt_no}
                            </button>
                          </TableCell>
                          <TableCell className="text-sm">{formatText(item.building_name)}</TableCell>
                          <TableCell className="text-sm">{formatText(item.struct_eng_name)}</TableCell>
                          <TableCell className="text-sm">
                            {formatText(item.latest_reviewer_name ?? item.reviewer_name)}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {formatLatestSubmission(item)}
                          </TableCell>
                          <TableCell className="text-sm">{formatResult(item.final_result)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            ) : (
              <div className="py-20 text-center text-muted-foreground">
                선택된 사무소가 없습니다.
              </div>
            )}
          </div>
        </div>
      )}

      <Dialog open={!!resolveTarget} onOpenChange={(open) => !open && setResolveTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>적합으로 변경하시겠습니까?</DialogTitle>
            <DialogDescription>
              {resolveTarget?.mgmt_no} 검토서의 확인 대상을 적합으로 처리합니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setResolveTarget(null)}
              disabled={resolvingId !== null}
            >
              아니오
            </Button>
            <Button
              type="button"
              onClick={handleConfirmSuitable}
              loading={resolvingId !== null}
              loadingText="처리 중"
            >
              예
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
