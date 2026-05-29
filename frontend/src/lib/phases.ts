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
