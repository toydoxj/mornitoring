"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"
import { PHASE_LABELS } from "@/types"

interface InquiryItem {
  id: number
  mgmt_no: string
  building_name: string | null
  reviewer_name: string | null
  phase: string
  inquiry: string
  created_at: string
}

interface InquiryListResponse {
  items: InquiryItem[]
  total: number
}

export default function InquiriesPage() {
  const [data, setData] = useState<InquiryItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const pageSize = 50

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true)
      try {
        const { data: res } = await apiClient.get<InquiryListResponse>(
          "/api/reviews/inquiries",
          { params: { page, size: pageSize } }
        )
        setData(res.items)
        setTotal(res.total)
      } catch (err) {
        console.error("문의사항 조회 실패:", err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchData()
  }, [page])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">문의사항</h1>
        <p className="text-sm text-muted-foreground">총 {total}건</p>
      </div>

      <div className="rounded-md border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">관리번호</TableHead>
              <TableHead>건물명</TableHead>
              <TableHead className="w-[80px]">검토위원</TableHead>
              <TableHead className="w-[100px]">단계</TableHead>
              <TableHead>문의 내용</TableHead>
              <TableHead className="w-[150px]">등록일시</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center">
                  로딩 중...
                </TableCell>
              </TableRow>
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                  문의사항이 없습니다
                </TableCell>
              </TableRow>
            ) : (
              data.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-mono font-medium">{item.mgmt_no}</TableCell>
                  <TableCell>{item.building_name || "-"}</TableCell>
                  <TableCell>{item.reviewer_name || "-"}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {PHASE_LABELS[item.phase] || item.phase}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm">{item.inquiry}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {new Date(item.created_at).toLocaleString("ko-KR")}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
            이전
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
            다음
          </Button>
        </div>
      )}
    </div>
  )
}
