"use client"

import { useState } from "react"
import { ClipboardList, Copy, FolderInput, FolderOpen, FolderOutput, MoveRight, Play, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import apiClient from "@/lib/api/client"

interface NotificationItem {
  reviewer_name: string
  count: number
  mgmt_nos: string[]
  message: string
  round?: string
  phase?: string
  report_due_date?: string
}

// 접수일 + N일을 YYYY-MM-DD 로 반환
const DEFAULT_DUE_DAYS = 14
function addDays(iso: string, days: number): string {
  const d = new Date(iso)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

interface ReceiveResult {
  updated: number
  not_found: string[]
  notifications: NotificationItem[]
}

type FolderOperation = "move" | "copy"

interface LocalFileHandle {
  kind: "file"
  name: string
  getFile: () => Promise<File>
  createWritable: () => Promise<LocalWritableFileStream>
  isSameEntry?: (other: LocalHandle) => Promise<boolean>
}

interface LocalDirectoryHandle {
  kind: "directory"
  name: string
  values: () => AsyncIterable<LocalHandle>
  getDirectoryHandle: (
    name: string,
    options?: { create?: boolean }
  ) => Promise<LocalDirectoryHandle>
  getFileHandle: (
    name: string,
    options?: { create?: boolean }
  ) => Promise<LocalFileHandle>
  removeEntry: (name: string, options?: { recursive?: boolean }) => Promise<void>
  isSameEntry?: (other: LocalHandle) => Promise<boolean>
}

type LocalHandle = LocalFileHandle | LocalDirectoryHandle

interface LocalWritableFileStream {
  write: (data: Blob | BufferSource | string) => Promise<void>
  close: () => Promise<void>
}

type WindowWithDirectoryPicker = Window & {
  showDirectoryPicker?: (options?: {
    id?: string
    mode?: "read" | "readwrite"
  }) => Promise<LocalDirectoryHandle>
}

interface FolderDistributionDetail {
  status: string
  item_name: string
  mgmt_no: string | null
  reviewer_name: string | null
  reviewer_dir_name: string | null
  destination: string | null
  reason: string | null
}

interface FolderDistributionResult {
  classified: number
  skipped: number
  dry_run: boolean
  operation: string
  overwrite: boolean
  assignment_count: number
  unassigned_building_count: number
  classified_mgmt_nos: string[]
  reviewer_counts: Record<string, number>
  details: FolderDistributionDetail[]
}

interface FolderAssignmentMap {
  assignment: Record<string, string>
  assignment_count: number
  unassigned_building_count: number
}

const MGMT_NO_PATTERN = /^(\d{4}-\d{4})/
const INVALID_DIR_CHARS = /[<>:"/\\|?*\x00-\x1F]/g

function extractMgmtNo(name: string): string | null {
  return MGMT_NO_PATTERN.exec(name)?.[1] ?? null
}

function safeDirName(name: string): string {
  return name.replace(INVALID_DIR_CHARS, "_").trim().replace(/[.]+$/g, "") || "미지정"
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return String(error)
}

function isDomExceptionName(error: unknown, name: string): boolean {
  return error instanceof DOMException && error.name === name
}

async function isSameEntry(
  left: LocalDirectoryHandle,
  right: LocalDirectoryHandle
): Promise<boolean> {
  if (!left.isSameEntry) return false
  return left.isSameEntry(right)
}

async function getDirectoryIfExists(
  directory: LocalDirectoryHandle,
  name: string
): Promise<LocalDirectoryHandle | null> {
  try {
    return await directory.getDirectoryHandle(name)
  } catch (error) {
    if (isDomExceptionName(error, "NotFoundError")) return null
    if (isDomExceptionName(error, "TypeMismatchError")) return null
    throw error
  }
}

async function entryExists(
  directory: LocalDirectoryHandle,
  name: string
): Promise<boolean> {
  try {
    await directory.getFileHandle(name)
    return true
  } catch (fileError) {
    if (
      !isDomExceptionName(fileError, "NotFoundError") &&
      !isDomExceptionName(fileError, "TypeMismatchError")
    ) {
      throw fileError
    }
  }

  try {
    await directory.getDirectoryHandle(name)
    return true
  } catch (dirError) {
    if (isDomExceptionName(dirError, "NotFoundError")) return false
    if (isDomExceptionName(dirError, "TypeMismatchError")) return true
    throw dirError
  }
}

async function copyEntry(
  entry: LocalHandle,
  targetDirectory: LocalDirectoryHandle
): Promise<void> {
  if (entry.kind === "file") {
    const file = await entry.getFile()
    const targetFile = await targetDirectory.getFileHandle(entry.name, {
      create: true,
    })
    const writable = await targetFile.createWritable()
    await writable.write(file)
    await writable.close()
    return
  }

  const nextTarget = await targetDirectory.getDirectoryHandle(entry.name, {
    create: true,
  })
  for await (const child of entry.values()) {
    await copyEntry(child, nextTarget)
  }
}

async function distributeLocalFolders({
  sourceHandle,
  targetHandle,
  assignment,
  dryRun,
  operation,
  overwrite,
  unassignedBuildingCount,
}: {
  sourceHandle: LocalDirectoryHandle
  targetHandle: LocalDirectoryHandle
  assignment: Record<string, string>
  dryRun: boolean
  operation: FolderOperation
  overwrite: boolean
  unassignedBuildingCount: number
}): Promise<FolderDistributionResult> {
  if (await isSameEntry(sourceHandle, targetHandle)) {
    throw new Error("접수 폴더와 배포 폴더는 같을 수 없습니다")
  }

  const details: FolderDistributionDetail[] = []
  const reviewerCounts: Record<string, number> = {}
  const classifiedMgmtNos: string[] = []
  const entries: LocalHandle[] = []

  for await (const entry of sourceHandle.values()) {
    entries.push(entry)
  }

  let classified = 0
  let skipped = 0

  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    try {
      if (entry.kind === "directory" && await isSameEntry(entry, targetHandle)) {
        skipped += 1
        details.push({
          status: "skipped",
          item_name: entry.name,
          mgmt_no: null,
          reviewer_name: null,
          reviewer_dir_name: null,
          destination: null,
          reason: "배포 폴더는 분배 대상에서 제외됩니다",
        })
        continue
      }

      const mgmtNo = extractMgmtNo(entry.name)
      if (!mgmtNo) {
        skipped += 1
        details.push({
          status: "skipped",
          item_name: entry.name,
          mgmt_no: null,
          reviewer_name: null,
          reviewer_dir_name: null,
          destination: null,
          reason: "관리번호 인식 불가",
        })
        continue
      }

      const reviewerName = assignment[mgmtNo]
      if (!reviewerName) {
        skipped += 1
        details.push({
          status: "skipped",
          item_name: entry.name,
          mgmt_no: mgmtNo,
          reviewer_name: null,
          reviewer_dir_name: null,
          destination: null,
          reason: "검토위원 미배정",
        })
        continue
      }

      const reviewerDirName = safeDirName(reviewerName)
      const existingReviewerDir = await getDirectoryIfExists(targetHandle, reviewerDirName)
      const reviewerDir = dryRun
        ? existingReviewerDir
        : await targetHandle.getDirectoryHandle(reviewerDirName, { create: true })
      const exists = reviewerDir ? await entryExists(reviewerDir, entry.name) : false

      if (exists && !overwrite) {
        skipped += 1
        details.push({
          status: "skipped",
          item_name: entry.name,
          mgmt_no: mgmtNo,
          reviewer_name: reviewerName,
          reviewer_dir_name: reviewerDirName,
          destination: `${targetHandle.name}/${reviewerDirName}/${entry.name}`,
          reason: "대상에 같은 이름이 이미 있습니다",
        })
        continue
      }

      if (!dryRun && reviewerDir) {
        if (exists) {
          await reviewerDir.removeEntry(entry.name, { recursive: true })
        }
        await copyEntry(entry, reviewerDir)
        if (operation === "move") {
          await sourceHandle.removeEntry(entry.name, { recursive: true })
        }
      }

      classified += 1
      reviewerCounts[reviewerName] = (reviewerCounts[reviewerName] ?? 0) + 1
      if (!classifiedMgmtNos.includes(mgmtNo)) {
        classifiedMgmtNos.push(mgmtNo)
      }
      details.push({
        status: exists ? "overwritten" : operation,
        item_name: entry.name,
        mgmt_no: mgmtNo,
        reviewer_name: reviewerName,
        reviewer_dir_name: reviewerDirName,
        destination: `${targetHandle.name}/${reviewerDirName}/${entry.name}`,
        reason: null,
      })
    } catch (error) {
      skipped += 1
      details.push({
        status: "skipped",
        item_name: entry.name,
        mgmt_no: extractMgmtNo(entry.name),
        reviewer_name: null,
        reviewer_dir_name: null,
        destination: null,
        reason: `처리 오류: ${getErrorMessage(error)}`,
      })
    }
  }

  return {
    classified,
    skipped,
    dry_run: dryRun,
    operation,
    overwrite,
    assignment_count: Object.keys(assignment).length,
    unassigned_building_count: unassignedBuildingCount,
    classified_mgmt_nos: classifiedMgmtNos,
    reviewer_counts: Object.fromEntries(
      Object.entries(reviewerCounts).sort(([a], [b]) => a.localeCompare(b))
    ),
    details,
  }
}

function getFolderStatusLabel(status: string) {
  if (status === "move") return "이동"
  if (status === "copy") return "복사"
  if (status === "overwritten") return "덮어쓰기"
  if (status === "skipped") return "스킵"
  return status
}

function getFolderStatusVariant(status: string): "default" | "secondary" | "outline" | "destructive" {
  if (status === "skipped") return "destructive"
  if (status === "overwritten") return "secondary"
  return "outline"
}

export default function DistributionPage() {
  const [sourceDir, setSourceDir] = useState("")
  const [targetDir, setTargetDir] = useState("")
  const [sourceHandle, setSourceHandle] = useState<LocalDirectoryHandle | null>(null)
  const [targetHandle, setTargetHandle] = useState<LocalDirectoryHandle | null>(null)
  const [folderOperation, setFolderOperation] = useState<FolderOperation>("move")
  const [folderOverwrite, setFolderOverwrite] = useState(false)
  const [folderResult, setFolderResult] = useState<FolderDistributionResult | null>(null)
  const [folderError, setFolderError] = useState<string | null>(null)
  const [isPreviewingFolders, setIsPreviewingFolders] = useState(false)
  const [isDistributingFolders, setIsDistributingFolders] = useState(false)

  const [mgmtNosInput, setMgmtNosInput] = useState("")
  const initialReceived = new Date().toISOString().slice(0, 10)
  const [receivedDate, setReceivedDate] = useState(initialReceived)
  // 검토서 요청 예정일 — 접수일 + DEFAULT_DUE_DAYS 기본값, 사용자가 직접 수정 가능
  const [reportDueDate, setReportDueDate] = useState(
    addDays(initialReceived, DEFAULT_DUE_DAYS)
  )
  // 예정일을 사용자가 한 번이라도 손댔으면 접수일 변경 시 더 이상 자동 계산하지 않는다
  const [dueDateTouched, setDueDateTouched] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [result, setResult] = useState<ReceiveResult | null>(null)
  const [notifSent, setNotifSent] = useState(false)

  const handleReceivedDateChange = (v: string) => {
    setReceivedDate(v)
    if (!dueDateTouched && v) {
      setReportDueDate(addDays(v, DEFAULT_DUE_DAYS))
    }
  }

  const handleDueDateChange = (v: string) => {
    setReportDueDate(v)
    setDueDateTouched(true)
  }

  const applyFolderMgmtNos = (nos: string[]) => {
    setMgmtNosInput(nos.join("\n"))
  }

  const pickFolder = async (kind: "source" | "target") => {
    const picker = (window as WindowWithDirectoryPicker).showDirectoryPicker
    if (!picker) {
      setFolderError("이 브라우저는 폴더 선택을 지원하지 않습니다. Chrome 또는 Edge에서 열어주세요.")
      return
    }

    try {
      const handle = await picker({
        id: kind === "source" ? "distribution-source" : "distribution-target",
        mode: "readwrite",
      })
      if (kind === "source") {
        setSourceHandle(handle)
        setSourceDir(handle.name)
      } else {
        setTargetHandle(handle)
        setTargetDir(handle.name)
      }
      setFolderError(null)
    } catch (error) {
      if (isDomExceptionName(error, "AbortError")) return
      setFolderError(`폴더 선택 실패: ${getErrorMessage(error)}`)
    }
  }

  const runFolderDistribution = async (dryRun: boolean) => {
    if (!sourceHandle) {
      alert("접수 폴더를 선택해주세요")
      return
    }
    if (!targetHandle) {
      alert("배포 폴더를 선택해주세요")
      return
    }

    if (dryRun) {
      setIsPreviewingFolders(true)
    } else {
      setIsDistributingFolders(true)
    }
    setFolderError(null)

    try {
      const { data } = await apiClient.get<FolderAssignmentMap>(
        "/api/distribution/folder-assignment-map"
      )
      if (data.assignment_count === 0) {
        setFolderError("DB에 검토위원이 배정된 관리번호가 없습니다")
        return
      }

      const distributionResult = await distributeLocalFolders({
        sourceHandle,
        targetHandle,
        assignment: data.assignment,
        dryRun,
        operation: folderOperation,
        overwrite: folderOverwrite,
        unassignedBuildingCount: data.unassigned_building_count,
      })
      setFolderResult(distributionResult)
      if (!dryRun && distributionResult.classified_mgmt_nos.length > 0) {
        applyFolderMgmtNos(distributionResult.classified_mgmt_nos)
      }
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { detail?: string } } }
      setFolderError(apiErr.response?.data?.detail || getErrorMessage(err) || "폴더 분배 처리에 실패했습니다")
    } finally {
      setIsPreviewingFolders(false)
      setIsDistributingFolders(false)
    }
  }

  const handleReceive = async () => {
    const mgmtNos = mgmtNosInput
      .split(/[\n,\s]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d{4}-\d{4}$/.test(s))

    if (mgmtNos.length === 0) {
      alert("관리번호를 입력해주세요")
      return
    }

    setIsProcessing(true)
    setResult(null)
    setNotifSent(false)

    try {
      const { data } = await apiClient.post<ReceiveResult>(
        "/api/distribution/receive",
        {
          mgmt_nos: mgmtNos,
          received_date: receivedDate,
          report_due_date: reportDueDate || null,
        }
      )
      setResult(data)
    } catch (err) {
      console.error("접수 처리 실패:", err)
    } finally {
      setIsProcessing(false)
    }
  }

  const [notifSending, setNotifSending] = useState(false)
  const [notifResult, setNotifResult] = useState<{ sent: number; failed: number; error?: string } | null>(null)

  const handleSendNotifications = async () => {
    if (!result) return
    setNotifSending(true)
    setNotifResult(null)

    try {
      const { data } = await apiClient.post("/api/distribution/notify", result.notifications)
      setNotifSent(true)
      setNotifResult(data)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { error?: string } } }
      setNotifResult({
        sent: 0,
        failed: result.notifications.length,
        error: axiosErr.response?.data?.error || "발송 요청 실패",
      })
    } finally {
      setNotifSending(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">도서 접수/배포</h1>
        <p className="text-sm text-muted-foreground">
          폴더명 관리번호를 DB 배정 검토위원과 매칭한 뒤 접수 처리와 알림 발송까지 이어서 진행합니다
        </p>
      </div>

      {/* 폴더 분배 */}
      <Card>
        <CardHeader>
          <CardTitle>1단계: 검토위원별 폴더 분배</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label>접수 폴더</Label>
              <div className="flex items-center gap-2">
                <FolderInput className="h-4 w-4 text-muted-foreground" />
                <Input
                  value={sourceDir}
                  readOnly
                  placeholder="폴더를 선택해주세요"
                />
                <Button variant="outline" onClick={() => pickFolder("source")}>
                  <FolderOpen />
                  선택
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <Label>배포 폴더</Label>
              <div className="flex items-center gap-2">
                <FolderOutput className="h-4 w-4 text-muted-foreground" />
                <Input
                  value={targetDir}
                  readOnly
                  placeholder="폴더를 선택해주세요"
                />
                <Button variant="outline" onClick={() => pickFolder("target")}>
                  <FolderOpen />
                  선택
                </Button>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-md border bg-background p-1">
              <Button
                variant={folderOperation === "move" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setFolderOperation("move")}
              >
                <MoveRight />
                이동
              </Button>
              <Button
                variant={folderOperation === "copy" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setFolderOperation("copy")}
              >
                <Copy />
                복사
              </Button>
            </div>
            <label className="flex h-8 items-center gap-2 rounded-md border px-3 text-sm">
              <input
                type="checkbox"
                checked={folderOverwrite}
                onChange={(e) => setFolderOverwrite(e.target.checked)}
                className="h-4 w-4"
              />
              같은 이름 덮어쓰기
            </label>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => runFolderDistribution(true)}
                loading={isPreviewingFolders}
                loadingText="확인 중..."
              >
                <Search />
                미리보기
              </Button>
              <Button
                onClick={() => runFolderDistribution(false)}
                loading={isDistributingFolders}
                loadingText="분배 중..."
              >
                <Play />
                분배 실행
              </Button>
            </div>
          </div>

          {folderError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">
              {folderError}
            </div>
          )}

          {folderResult && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Badge variant="default">
                  {folderResult.dry_run ? "분배 예정" : "분배 완료"} {folderResult.classified}건
                </Badge>
                <Badge variant={folderResult.skipped > 0 ? "destructive" : "outline"}>
                  스킵 {folderResult.skipped}건
                </Badge>
                <Badge variant="outline">DB 매핑 {folderResult.assignment_count}건</Badge>
                {folderResult.unassigned_building_count > 0 && (
                  <Badge variant="secondary">
                    미배정 {folderResult.unassigned_building_count}건
                  </Badge>
                )}
              </div>

              {Object.keys(folderResult.reviewer_counts).length > 0 && (
                <div className="flex flex-wrap gap-2 text-sm">
                  {Object.entries(folderResult.reviewer_counts).map(([name, count]) => (
                    <Badge key={name} variant="outline">
                      {name} {count}건
                    </Badge>
                  ))}
                </div>
              )}

              {folderResult.classified_mgmt_nos.length > 0 && (
                <Button
                  variant="outline"
                  onClick={() => applyFolderMgmtNos(folderResult.classified_mgmt_nos)}
                >
                  <ClipboardList />
                  접수 목록에 반영
                </Button>
              )}

              <div className="max-h-80 overflow-y-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[90px]">상태</TableHead>
                      <TableHead>폴더/파일명</TableHead>
                      <TableHead className="w-[110px]">관리번호</TableHead>
                      <TableHead className="w-[120px]">검토위원</TableHead>
                      <TableHead>대상 경로</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {folderResult.details.map((item, i) => (
                      <TableRow key={`${item.item_name}-${i}`}>
                        <TableCell>
                          <Badge variant={getFolderStatusVariant(item.status)}>
                            {getFolderStatusLabel(item.status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium">{item.item_name}</TableCell>
                        <TableCell className="font-mono text-xs">
                          {item.mgmt_no ?? "-"}
                        </TableCell>
                        <TableCell>{item.reviewer_name ?? "-"}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {item.reason ?? item.destination ?? "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 접수 입력 */}
      <Card>
        <CardHeader>
          <CardTitle>2단계: 접수 관리번호 입력</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-4">
            <div className="space-y-2">
              <Label>접수 날짜</Label>
              <Input
                type="date"
                value={receivedDate}
                onChange={(e) => handleReceivedDateChange(e.target.value)}
                className="w-48"
              />
            </div>
            <div className="space-y-2">
              <Label>검토서 요청 예정일</Label>
              <Input
                type="date"
                value={reportDueDate}
                onChange={(e) => handleDueDateChange(e.target.value)}
                className="w-48"
              />
              <p className="text-xs text-muted-foreground">
                기본값: 접수일 + {DEFAULT_DUE_DAYS}일 (직접 수정 가능)
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label>관리번호 (줄바꿈 또는 쉼표로 구분)</Label>
            <textarea
              className="w-full min-h-[150px] rounded-md border px-3 py-2 text-sm font-mono"
              placeholder={"2025-0001\n2025-0002\n2025-0003"}
              value={mgmtNosInput}
              onChange={(e) => setMgmtNosInput(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              입력된 관리번호 수:{" "}
              {
                mgmtNosInput
                  .split(/[\n,\s]+/)
                  .filter((s) => /^\d{4}-\d{4}$/.test(s.trim())).length
              }
              건
            </p>
          </div>

          <Button onClick={handleReceive} loading={isProcessing} loadingText="처리 중...">
            접수 처리
          </Button>
        </CardContent>
      </Card>

      {/* 처리 결과 */}
      {result && (
        <Card>
          <CardHeader>
            <CardTitle>3단계: 접수 결과 확인</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-3">
              <Badge variant="default">접수 완료 {result.updated}건</Badge>
              {result.not_found.length > 0 && (
                <Badge variant="destructive">
                  관리번호 없음 {result.not_found.length}건
                </Badge>
              )}
            </div>

            {result.not_found.length > 0 && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">
                <p className="font-medium">찾을 수 없는 관리번호:</p>
                <p className="font-mono">{result.not_found.join(", ")}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 알림 발송 */}
      {result && result.notifications.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>4단계: 검토위원 알림 발송</CardTitle>
            <Button
              onClick={handleSendNotifications}
              disabled={notifSent}
              loading={notifSending}
              loadingText="발송 중..."
            >
              {notifSent ? "발송 완료" : "카카오톡 알림 발송"}
            </Button>
          </CardHeader>
          <CardContent>
            {notifResult && (
              <div className={`rounded-md p-3 text-sm mb-4 ${
                notifResult.sent > 0 ? "bg-green-50 text-green-800" : "bg-yellow-50 text-yellow-800"
              }`}>
                <p>발송 성공: <strong>{notifResult.sent}건</strong> / 실패: {notifResult.failed}건</p>
                {notifResult.error && <p className="text-red-600 mt-1">{notifResult.error}</p>}
                {notifResult.failed > 0 && !notifResult.error && (
                  <p className="mt-1 text-muted-foreground">실패 상세는 알림 현황 페이지에서 확인하세요</p>
                )}
              </div>
            )}
            <div className="rounded-md border max-h-96 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>검토위원</TableHead>
                    <TableHead className="w-[100px]">차수</TableHead>
                    <TableHead className="w-[60px]">건수</TableHead>
                    <TableHead>알림 내용</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.notifications.map((n, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{n.reviewer_name}</TableCell>
                      <TableCell>
                        {n.round ? (
                          <Badge variant="outline">{n.round}</Badge>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>{n.count}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {n.message}
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
