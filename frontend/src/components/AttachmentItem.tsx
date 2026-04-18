"use client"

import { FileIcon, X } from "lucide-react"
import { Button } from "@/components/ui/button"

export interface AttachmentDisplay {
  id: number
  filename: string
  file_size: number
  content_type?: string | null
  uploaded_by: number
  download_url?: string | null
}

// SVG 는 스크립트 삽입 우려가 있어 인라인 렌더에서 제외 (다운로드만 허용)
const IMAGE_EXTS = ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif"]

function isImage(a: AttachmentDisplay): boolean {
  const ct = a.content_type ?? ""
  if (ct.startsWith("image/") && !ct.includes("svg")) return true
  const ext = a.filename.split(".").pop()?.toLowerCase() ?? ""
  return IMAGE_EXTS.includes(ext)
}

function formatKB(size: number): string {
  return `${(size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB`
}

export function AttachmentItem({
  attachment,
  canDelete,
  onDelete,
  onDownload,
}: {
  attachment: AttachmentDisplay
  canDelete: boolean
  onDelete: () => void
  /** download_url 이 없을 때 별도 endpoint 호출로 URL 얻을 콜백. 생략 시 download_url 만 사용 */
  onDownload?: () => void
}) {
  const url = attachment.download_url ?? null

  if (url && isImage(attachment)) {
    return (
      <div className="overflow-hidden rounded-md border">
        <div className="flex items-center justify-between gap-2 border-b bg-slate-50 px-3 py-1.5 text-sm">
          <span className="truncate">{attachment.filename}</span>
          <div className="flex items-center gap-2">
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatKB(attachment.file_size)}
            </span>
            {canDelete && (
              <Button size="icon-xs" variant="ghost" onClick={onDelete} aria-label="삭제">
                <X />
              </Button>
            )}
          </div>
        </div>
        <a href={url} target="_blank" rel="noopener noreferrer" className="block bg-slate-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt={attachment.filename}
            className="mx-auto max-h-[480px] w-auto object-contain"
            loading="lazy"
          />
        </a>
      </div>
    )
  }

  const handleClick = () => {
    if (onDownload) onDownload()
    else if (url) window.open(url, "_blank", "noopener,noreferrer")
  }

  return (
    <div className="flex items-center gap-2 rounded-md border p-2 text-sm">
      <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <button
        className="flex-1 truncate text-left text-blue-600 hover:underline"
        onClick={handleClick}
      >
        {attachment.filename}
      </button>
      <span className="shrink-0 text-xs text-muted-foreground">
        {formatKB(attachment.file_size)}
      </span>
      {canDelete && (
        <Button size="icon-xs" variant="ghost" onClick={onDelete} aria-label="삭제">
          <X />
        </Button>
      )}
    </div>
  )
}
