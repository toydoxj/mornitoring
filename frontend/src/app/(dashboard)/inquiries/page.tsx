"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { PHASE_LABELS } from "@/types"

interface InquiryItem {
  id: number
  building_id: number
  mgmt_no: string
  phase: string
  submitter_name: string
  content: string
  reply: string | null
  status: string
  created_at: string
  updated_at: string
}

interface InquiryListResponse {
  items: InquiryItem[]
  total: number
}

const STATUS_LABELS: Record<string, string> = {
  open: "접수",
  asking_agency: "관리원문의중",
  completed: "완료",
  next_phase: "다음단계",
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  open: "destructive",
  asking_agency: "secondary",
  completed: "default",
  next_phase: "default",
}

export default function InquiriesPage() {
  const [activeData, setActiveData] = useState<InquiryItem[]>([])
  const [activeTotal, setActiveTotal] = useState(0)
  const [closedData, setClosedData] = useState<InquiryItem[]>([])
  const [closedTotal, setClosedTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [replyMap, setReplyMap] = useState<Record<number, string>>({})

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const [activeRes, closedRes] = await Promise.all([
        apiClient.get<InquiryListResponse>("/api/reviews/inquiries", { params: { status_filter: "active", size: 200 } }),
        apiClient.get<InquiryListResponse>("/api/reviews/inquiries", { params: { status_filter: "closed", size: 200 } }),
      ])
      setActiveData(activeRes.data.items)
      setActiveTotal(activeRes.data.total)
      setClosedData(closedRes.data.items)
      setClosedTotal(closedRes.data.total)

      // 기존 답변 로드
      const map: Record<number, string> = {}
      for (const item of activeRes.data.items) {
        if (item.reply) map[item.id] = item.reply
      }
      setReplyMap(map)
    } catch (err) {
      console.error("문의사항 조회 실패:", err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleUpdate = async (id: number, status: string) => {
    try {
      await apiClient.patch(`/api/reviews/inquiry/${id}`, {
        reply: replyMap[id] || null,
        status,
      })
      fetchData()
    } catch (err) {
      console.error("업데이트 실패:", err)
    }
  }

  const handleReplyOnly = async (id: number) => {
    try {
      await apiClient.patch(`/api/reviews/inquiry/${id}`, {
        reply: replyMap[id] || "",
      })
      alert("답변이 저장되었습니다")
    } catch (err) {
      console.error("답변 저장 실패:", err)
    }
  }

  if (isLoading) {
    return <div className="flex justify-center py-20 text-muted-foreground">로딩 중...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">문의사항</h1>
        <p className="text-sm text-muted-foreground">
          진행중 {activeTotal}건 / 완료 {closedTotal}건
        </p>
      </div>

      {/* 진행중 문의 */}
      <div>
        <h2 className="text-lg font-semibold mb-2">진행중</h2>
        <div className="rounded-md border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">관리번호</TableHead>
                <TableHead className="w-[70px]">검토위원</TableHead>
                <TableHead className="w-[80px]">단계</TableHead>
                <TableHead>문의 내용</TableHead>
                <TableHead className="w-[250px]">답변</TableHead>
                <TableHead className="w-[80px]">상태</TableHead>
                <TableHead className="w-[280px]">처리</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activeData.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-20 text-center text-muted-foreground">
                    진행중인 문의가 없습니다
                  </TableCell>
                </TableRow>
              ) : (
                activeData.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono text-sm">
                      <Link
                        href={`/buildings/${item.building_id}`}
                        className="text-primary hover:underline"
                      >
                        {item.mgmt_no}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">{item.submitter_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {PHASE_LABELS[item.phase] || item.phase}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{item.content}</TableCell>
                    <TableCell>
                      <Input
                        value={replyMap[item.id] ?? item.reply ?? ""}
                        onChange={(e) => setReplyMap({ ...replyMap, [item.id]: e.target.value })}
                        placeholder="답변 입력"
                        className="text-sm"
                      />
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[item.status]}>
                        {STATUS_LABELS[item.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        <Button size="sm" variant="outline" onClick={() => handleReplyOnly(item.id)}>
                          답변저장
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => handleUpdate(item.id, "asking_agency")}>
                          관리원문의
                        </Button>
                        <Button size="sm" variant="default" onClick={() => handleUpdate(item.id, "completed")}>
                          완료
                        </Button>
                        <Button size="sm" variant="default" onClick={() => handleUpdate(item.id, "next_phase")}>
                          다음단계
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 완료된 문의 */}
      {closedData.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-2">완료/다음단계</h2>
          <div className="rounded-md border bg-white">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[100px]">관리번호</TableHead>
                  <TableHead className="w-[70px]">검토위원</TableHead>
                  <TableHead className="w-[80px]">단계</TableHead>
                  <TableHead>문의 내용</TableHead>
                  <TableHead>답변</TableHead>
                  <TableHead className="w-[80px]">상태</TableHead>
                  <TableHead className="w-[130px]">처리일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {closedData.map((item) => (
                  <TableRow key={item.id} className="text-muted-foreground">
                    <TableCell className="font-mono text-sm">
                      <Link
                        href={`/buildings/${item.building_id}`}
                        className="text-primary hover:underline"
                      >
                        {item.mgmt_no}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm">{item.submitter_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {PHASE_LABELS[item.phase] || item.phase}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{item.content}</TableCell>
                    <TableCell className="text-sm">{item.reply || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[item.status]}>
                        {STATUS_LABELS[item.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {new Date(item.updated_at).toLocaleString("ko-KR")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  )
}
