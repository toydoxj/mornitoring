export const WORKFLOW_PHASE_SEQUENCE = [
  "assigned",
  "doc_received",
  "preliminary",
  "supplement_1_received",
  "supplement_1",
  "supplement_2_received",
  "supplement_2",
  "supplement_3_received",
  "supplement_3",
  "supplement_4_received",
  "supplement_4",
  "supplement_5_received",
  "supplement_5",
] as const

export function getAdjacentManualPhases(currentPhase: string | null | undefined): string[] {
  if (!currentPhase) return []

  const index = WORKFLOW_PHASE_SEQUENCE.findIndex((phase) => phase === currentPhase)
  if (index < 0) return []

  const phases: string[] = []
  const previous = WORKFLOW_PHASE_SEQUENCE[index - 1]
  const next = WORKFLOW_PHASE_SEQUENCE[index + 1]
  if (previous) phases.push(previous)
  if (next) phases.push(next)
  return phases
}

/** 재제출 요청 시 되돌아갈 이전 단계. 접수 상태가 아니면 null. */
export function getResubmitPreviousPhase(
  currentPhase: string | null | undefined
): string | null {
  if (!currentPhase || !currentPhase.endsWith("_received")) return null

  const index = WORKFLOW_PHASE_SEQUENCE.findIndex((phase) => phase === currentPhase)
  if (index <= 0) return null
  return WORKFLOW_PHASE_SEQUENCE[index - 1]
}
