"use client"

import { useParams, useSearchParams } from "next/navigation"
import { BuildingDetailView } from "@/components/BuildingDetailView"

export default function BuildingDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()

  return (
    <BuildingDetailView
      buildingId={String(params.id)}
      from={searchParams.get("from")}
      returnTo={searchParams.get("returnTo")}
      editPhaseParam={searchParams.get("editPhase") === "1"}
    />
  )
}
