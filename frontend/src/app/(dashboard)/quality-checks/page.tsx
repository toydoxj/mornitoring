"use client"

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { CheckCircle2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"

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

function formatList(values: string[]) {
  return values.length > 0 ? values.join(", ") : "-"
}

export default function QualityChecksPage() {
  const router = useRouter()
  const [items, setItems] = useState<QualityCheckItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [resolveTarget, setResolveTarget] = useState<QualityCheckItem | null>(null)
  const [resolvingId, setResolvingId] = useState<number | null>(null)

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

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

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

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">검토서 확인</h1>
          <p className="text-sm text-muted-foreground">
            심각도 L3/L4 또는 표현 품질 점검 대상 검토서 {total.toLocaleString()}건
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={fetchItems}
          loading={isLoading}
          loadingText="조회 중"
        >
          <RefreshCw />
          새로고침
        </Button>
      </div>

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
