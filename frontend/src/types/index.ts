// 사용자 역할
export type UserRole = "team_leader" | "chief_secretary" | "secretary" | "reviewer"

// 사용자
export interface User {
  id: number
  name: string
  email: string
  role: UserRole
  phone: string | null
  is_active: boolean
  kakao_linked?: boolean
}

// 건축물 (통합관리대장)
export interface Building {
  id: number
  mgmt_no: string
  building_name: string | null
  sido: string | null
  sigungu: string | null
  beopjeongdong: string | null
  main_lot_no: string | null
  sub_lot_no: string | null
  special_lot_no: string | null
  main_structure: string | null
  main_usage: string | null
  gross_area: number | null
  floors_above: number | null
  floors_below: number | null
  high_risk_type: string | null
  current_phase: string | null
  final_result: string | null
  reviewer_id: number | null
  reviewer_name: string | null
  assigned_reviewer_name: string | null
  reviewer_registered: boolean
  // 내 검토대상 파생 필드
  full_address?: string | null
  latest_result?: string | null
  latest_inappropriate?: boolean
}

export interface BuildingListResponse {
  items: Building[]
  total: number
}

// 검토 단계
export type PhaseType =
  | "preliminary"
  | "supplement_1"
  | "supplement_2"
  | "supplement_3"
  | "supplement_4"
  | "supplement_5"

export type ResultType = "pass" | "simple_error" | "recalculate"

export interface ReviewStage {
  id: number
  building_id: number
  phase: PhaseType
  phase_order: number
  doc_received_at: string | null
  report_submitted_at: string | null
  reviewer_name: string | null
  result: ResultType | null
  review_opinion: string | null
  defect_type_1: string | null
  defect_type_2: string | null
  defect_type_3: string | null
}

// 역할 한글 라벨
export const ROLE_LABELS: Record<UserRole, string> = {
  team_leader: "팀장",
  chief_secretary: "총괄간사",
  secretary: "간사",
  reviewer: "검토위원",
}

// 단계 한글 라벨
// 흐름: 예비도서 접수 → 예비검토서 제출 → 보완도서(1차) 접수 → 보완검토서(1차) 제출 → ...
export const PHASE_LABELS: Record<string, string> = {
  doc_received: "예비도서 접수",
  preliminary: "예비검토서 제출",
  supplement_1_received: "보완도서(1차) 접수",
  supplement_1: "보완검토서(1차) 제출",
  supplement_2_received: "보완도서(2차) 접수",
  supplement_2: "보완검토서(2차) 제출",
  supplement_3_received: "보완도서(3차) 접수",
  supplement_3: "보완검토서(3차) 제출",
  supplement_4_received: "보완도서(4차) 접수",
  supplement_4: "보완검토서(4차) 제출",
  supplement_5_received: "보완도서(5차) 접수",
  supplement_5: "보완검토서(5차) 제출",
  completed: "완료",
}

// 결과 한글 라벨
export const RESULT_LABELS: Record<ResultType, string> = {
  pass: "적합",
  simple_error: "단순오류",
  recalculate: "재계산",
}
