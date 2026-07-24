"use client"

import { useCallback, useState } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { BuildingDetailView } from "@/components/BuildingDetailView"

/**
 * 목록 화면에서 관리번호를 눌렀을 때 건축물 상세 화면을 그대로 띄우는 팝업.
 * `/buildings/[id]` 페이지와 동일한 본문(BuildingDetailView)을 사용한다.
 */
export function BuildingDetailDialog({
  buildingId,
  onClose,
}: {
  buildingId: number | null
  onClose: () => void
}) {
  const [notFound, setNotFound] = useState(false)
  const handleNotFound = useCallback(() => setNotFound(true), [])

  return (
    <Dialog
      open={buildingId !== null}
      onOpenChange={(open) => {
        if (!open) {
          setNotFound(false)
          onClose()
        }
      }}
    >
      <DialogContent className="max-h-[90vh] w-[min(1200px,calc(100vw-2rem))] max-w-none overflow-y-auto p-6 sm:max-w-none">
        <DialogTitle className="sr-only">건축물 상세</DialogTitle>
        {buildingId !== null &&
          (notFound ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              건축물을 찾을 수 없습니다.
            </div>
          ) : (
            <BuildingDetailView
              key={buildingId}
              buildingId={String(buildingId)}
              embedded
              onNotFound={handleNotFound}
            />
          ))}
      </DialogContent>
    </Dialog>
  )
}
