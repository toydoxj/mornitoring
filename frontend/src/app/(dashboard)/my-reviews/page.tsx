"use client"

import { useEffect, useState } from "react"
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
import type { Building, BuildingListResponse, PhaseType, ResultType } from "@/types"
import { PHASE_LABELS, RESULT_LABELS } from "@/types"

const RESULT_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pass: "default",
  supplement: "secondary",
  fail: "destructive",
  minor: "outline",
}

export default function MyReviewsPage() {
  const [data, setData] = useState<Building[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const fetch = async () => {
      try {
        const { data: res } = await apiClient.get<BuildingListResponse>(
          "/api/buildings/my-reviews"
        )
        setData(res.items)
        setTotal(res.total)
      } catch (err) {
        console.error("검토 대상 조회 실패:", err)
      } finally {
        setIsLoading(false)
      }
    }
    fetch()
  }, [])

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">내 검토 대상</h1>
        <p className="text-sm text-muted-foreground">
          배정된 검토 대상 {total}건
        </p>
      </div>

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">관리번호</TableHead>
              <TableHead>건물명</TableHead>
              <TableHead>주소</TableHead>
              <TableHead className="w-[100px]">연면적(㎡)</TableHead>
              <TableHead className="w-[80px]">지상층</TableHead>
              <TableHead className="w-[100px]">현재 단계</TableHead>
              <TableHead className="w-[90px]">최종 판정</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  배정된 검토 대상이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((b) => (
                <TableRow key={b.id} className="cursor-pointer hover:bg-muted/50">
                  <TableCell className="font-mono font-medium">{b.mgmt_no}</TableCell>
                  <TableCell>{b.building_name || "-"}</TableCell>
                  <TableCell>
                    {[b.sido, b.sigungu, b.beopjeongdong].filter(Boolean).join(" ") || "-"}
                  </TableCell>
                  <TableCell>{b.gross_area?.toLocaleString() ?? "-"}</TableCell>
                  <TableCell>{b.floors_above ?? "-"}</TableCell>
                  <TableCell>
                    {b.current_phase
                      ? PHASE_LABELS[b.current_phase as PhaseType] || b.current_phase
                      : "-"}
                  </TableCell>
                  <TableCell>
                    {b.final_result ? (
                      <Badge variant={RESULT_VARIANT[b.final_result] || "outline"}>
                        {RESULT_LABELS[b.final_result as ResultType] || b.final_result}
                      </Badge>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
