"use client"

import { useState } from "react"
import Link from "next/link"
import type { LucideIcon } from "lucide-react"
import {
  AlertTriangle,
  Bell,
  BookOpenCheck,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  FileQuestion,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  Layers,
  LinkIcon,
  MessageSquare,
  ShieldAlert,
  UploadCloud,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import apiClient from "@/lib/api/client"

interface ManualStep {
  step: string
  title: string
  description: string
  details: string[]
  icon: LucideIcon
}

interface GuideSection {
  title: string
  description: string
  items: string[]
  icon: LucideIcon
}

interface SeverityLevel {
  level: string
  name: string
  summary: string
  action: string
  tone: string
}

interface ValidationGroup {
  title: string
  items: string[]
}

interface FaqItem {
  question: string
  answer: string
}

interface ProgramImprovementResponse {
  message: string
  is_sent: boolean
  recipient_id: number
  recipient_name: string
  error: string | null
}

type ApiDetail = string | { message?: string } | { msg?: string }[]

interface ApiError {
  response?: {
    data?: {
      detail?: ApiDetail
    }
  }
}

const taskFacts = [
  { label: "과업", value: "건축안전 모니터링 구조분야 설계도서 검토" },
  { label: "대상", value: "5,000동 검토, 고위험군 500동 포함" },
  { label: "기간", value: "착수일 ~ 2026.12.15." },
  { label: "알림", value: "제출 D-3부터 카카오톡 알림" },
]

const workflowSteps: ManualStep[] = [
  {
    step: "1",
    title: "최초 접속",
    description: "카카오톡으로 받은 링크에서 비밀번호를 설정하고 로그인합니다.",
    details: [
      "아이디는 등록된 이메일 주소를 사용합니다.",
      "로그인 후 카카오톡 연동을 완료해야 업무 배정과 알림 수신이 원활합니다.",
    ],
    icon: LinkIcon,
  },
  {
    step: "2",
    title: "공지·토론 확인",
    description: "양식 파일, 기준 자료, 공통 쟁점을 먼저 확인합니다.",
    details: [
      "공지사항에는 검토의견서 양식과 주요 안내가 올라옵니다.",
      "의견 작성 기준처럼 여러 위원에게 공유할 질문은 토론방에 남깁니다.",
    ],
    icon: MessageSquare,
  },
  {
    step: "3",
    title: "도서 수신",
    description: "도서 배포 카카오톡 알림을 받은 뒤 웹하드에서 자료를 내려받습니다.",
    details: [
      "2026년 자료는 기초자료와 보완자료 중심으로 단순 분류됩니다.",
      "폴더명은 배포일 기준으로 공지될 수 있으니 공지사항을 함께 확인합니다.",
    ],
    icon: Bell,
  },
  {
    step: "4",
    title: "내 검토 확인",
    description: "시스템의 내 검토 대상에서 주소, 동, 관여 여부, 난이도를 확인합니다.",
    details: [
      "주소와 건물명이 실제 검토 대상과 맞는지 먼저 확인합니다.",
      "본인 또는 소속 사무실이 설계에 관여했거나 전문분야가 맞지 않으면 문의합니다.",
    ],
    icon: ClipboardList,
  },
  {
    step: "5",
    title: "검토서 작성",
    description: "배포된 xlsm 양식을 유지한 채 검토 의견과 심각도를 입력합니다.",
    details: [
      "파일명과 내부 관리번호가 관리번호와 일치해야 합니다.",
      "양식의 페이지 밖 여백은 수정하지 말고, 내용 추가는 행 삽입으로 처리합니다.",
    ],
    icon: FileSpreadsheet,
  },
  {
    step: "6",
    title: "문의·제출",
    description: "확인이 필요한 사항은 문의로 남기고, 검증 통과 후 검토서를 업로드합니다.",
    details: [
      "간단한 문의는 목록의 문의 버튼, 첨부가 필요한 문의는 상세 화면을 사용합니다.",
      "미리보기 검증 결과를 확인한 뒤 최종 업로드합니다.",
    ],
    icon: UploadCloud,
  },
]

const systemSections: GuideSection[] = [
  {
    title: "대시보드",
    description: "담당 현황과 미제출 일정을 보는 시작 화면입니다.",
    items: [
      "배정 건수와 제출 일정 현황을 확인합니다.",
      "내가 받은 카카오 알림과 문의 처리 현황을 확인합니다.",
      "공지사항과 토론방 최신 글을 빠르게 확인합니다.",
    ],
    icon: BookOpenCheck,
  },
  {
    title: "공지사항",
    description: "검토 기준과 양식 파일을 확인하는 화면입니다.",
    items: [
      "검토의견서 양식, 기준 자료, 운영 변경 사항을 확인합니다.",
      "양식이 변경되면 기존 파일이 아닌 최신 공지의 파일을 사용합니다.",
    ],
    icon: FileText,
  },
  {
    title: "토론방",
    description: "검토위원 간 공통 쟁점을 논의하는 공간입니다.",
    items: [
      "의견 작성 기준, 해석 관점처럼 여러 위원이 참고할 내용을 공유합니다.",
      "파일 첨부가 가능하므로 공통 참고자료를 함께 올릴 수 있습니다.",
    ],
    icon: MessageSquare,
  },
  {
    title: "내 검토 대상",
    description: "배정 건물 확인, 문의, 검토서 제출을 처리하는 핵심 화면입니다.",
    items: [
      "관리번호를 누르면 상세 화면으로 이동합니다.",
      "고위험군과 부적합 대상 표시를 확인합니다.",
      "업로드 버튼으로 검토서를 제출하고 문의 버튼으로 간사진에게 질의합니다.",
    ],
    icon: ClipboardCheck,
  },
]

const reviewChecks: GuideSection[] = [
  {
    title: "주소 확인",
    description: "내 검토 대상과 실제 도서의 주소가 같은지 확인합니다.",
    items: [
      "동일 허가건 안에 여러 동이 포함될 수 있으므로 주소와 동 정보를 함께 봅니다.",
    ],
    icon: Layers,
  },
  {
    title: "동·건물명 확인",
    description: "본인에게 배정된 동의 자료인지 확인합니다.",
    items: [
      "본인 대상이 아닌 동 자료가 섞여 있으면 바로 문의합니다.",
    ],
    icon: ClipboardList,
  },
  {
    title: "설계 관여 여부",
    description: "본인 또는 소속 사무실이 설계에 관여했는지 확인합니다.",
    items: [
      "이해관계가 확인되면 검토를 진행하지 말고 문의로 알려야 합니다.",
    ],
    icon: ShieldAlert,
  },
  {
    title: "검토 난이도",
    description: "목구조, 막구조, 면진 등 전문분야 검토 가능 여부를 판단합니다.",
    items: [
      "전문분야가 맞지 않으면 검토위원 교체가 필요할 수 있습니다.",
    ],
    icon: HelpCircle,
  },
]

const severityLevels: SeverityLevel[] = [
  {
    level: "L0",
    name: "누락",
    summary: "주요 도서나 계산근거가 없어 판정할 수 없는 상태",
    action: "보완 후 L1~L4로 재분류",
    tone: "bg-slate-50 text-slate-900",
  },
  {
    level: "L1",
    name: "경미",
    summary: "구조 안전성 영향이 없는 표기 오류나 오타",
    action: "단순 정정",
    tone: "bg-emerald-50 text-emerald-900",
  },
  {
    level: "L2",
    name: "일반",
    summary: "기준 적용 미흡 등 구조 안전성 영향이 크지 않은 오류",
    action: "단순 오류",
    tone: "bg-sky-50 text-sky-900",
  },
  {
    level: "L3",
    name: "중대",
    summary: "해석 모델 오류, 사용성 한계 초과, 주요 상세 누락 등 재해석이 필요한 사항",
    action: "재계산 필수",
    tone: "bg-amber-50 text-amber-900",
  },
  {
    level: "L4",
    name: "치명",
    summary: "구조 안전성을 훼손할 수 있는 계산 오류나 부재 내력 부족",
    action: "재계산 필수",
    tone: "bg-red-50 text-red-900",
  },
]

const validationGroups: ValidationGroup[] = [
  {
    title: "파일·권한",
    items: [
      ".xlsm 파일만 업로드할 수 있습니다.",
      "파일 크기는 10MB 이하로 준비합니다.",
      "파일명은 관리번호로 시작해야 하며 본인 담당 건만 업로드할 수 있습니다.",
    ],
  },
  {
    title: "엑셀 구조",
    items: [
      "검토서 시트와 내부 관리번호를 확인합니다.",
      "검토위원 이름은 로그인 사용자와 일치해야 합니다.",
      "매크로나 수식이 손상되지 않도록 양식을 임의 수정하지 않습니다.",
    ],
  },
  {
    title: "단계·차수",
    items: [
      "예비검토는 1차 적정성 검토 양식을 사용합니다.",
      "보완검토는 2차 적정성 검토 양식을 사용합니다.",
      "현재 단계와 검토서 차수가 다르면 검증에 실패할 수 있습니다.",
    ],
  },
  {
    title: "판정·심각도",
    items: [
      "적합이면 부적합 유형은 비워야 합니다.",
      "상세 의견이 있으면 부적합 유형과 심각도를 함께 입력합니다.",
      "L3 또는 L4가 하나라도 있으면 재계산 대상으로 분류합니다.",
    ],
  },
]

const writingCautions = [
  "페이지 밖 여백과 숨겨진 수식 영역은 수정하지 않습니다.",
  "검토 의견을 추가할 때는 셀을 밀지 말고 행 삽입으로 처리합니다.",
  "제출 전 행번호 자동 정리 기능을 실행합니다.",
  "구조도면 작성자 정보가 누락되지 않았는지 확인합니다.",
  "xlsm 보안 차단이 뜨면 파일 속성에서 읽기 전용을 해제하고 차단 해제를 체크합니다.",
]

const poorOpinionExamples = [
  "근거 없는 주관적 표현이나 감정적 표현",
  "관련 법령, 기준, 도면 위치 없이 결론만 적은 의견",
  "검토 범위 밖 사항에 대한 임의 지적",
  "특정 업체나 인물을 비판하는 표현",
]

const faqs: FaqItem[] = [
  {
    question: "이전 도서와 다른 자료가 다시 접수되었습니다.",
    answer: "새로 접수된 도서를 기준으로 검토서를 재제출합니다. 누락 도서가 보완되어 다시 접수되는 경우가 있습니다.",
  },
  {
    question: "검토서 제출 후 동일한 도서가 다시 접수되었습니다.",
    answer: "문의사항에 이전 단계 도서와 동일하다는 내용을 남기면 간사가 확인 후 처리합니다.",
  },
  {
    question: "검토서 작성 중 예비도서가 다시 접수되었습니다.",
    answer: "아직 미제출 상태라면 최종 접수된 도서를 기준으로 예비검토서를 작성합니다.",
  },
  {
    question: "도서가 검토 불가 수준으로 누락되었습니다.",
    answer: "단순히 도서 누락이라고 쓰기보다 어떤 검토를 위해 어떤 자료가 필요한지 구체적으로 적어 업로드합니다.",
  },
  {
    question: "이의제기서가 함께 접수되었습니다.",
    answer: "국토안전관리원이 이의제기를 수용하지 않은 건일 수 있으므로, 접수 도서를 근거로 검토서를 작성합니다.",
  },
  {
    question: "전문분야가 맞지 않아 검토가 어렵습니다.",
    answer: "문의사항에 검토위원 교체 요청을 남깁니다. 목구조, 막구조, 면진구조 등은 별도 편성이 필요할 수 있습니다.",
  },
  {
    question: "관계기술전문가 날인이 잘못되어 있습니다.",
    answer: "책임구조기술사 칸은 비워두고 문의사항에 내용을 남기면 간사가 확인 후 처리합니다.",
  },
  {
    question: "관리시스템 오류가 발생했습니다.",
    answer: "조별 간사에게 알려주세요. 복구 전까지 필요한 업무는 간사가 대신 처리할 수 있습니다.",
  },
]

export default function ReviewerManualPage() {
  const [improvementOpen, setImprovementOpen] = useState(false)
  const [improvementContent, setImprovementContent] = useState("")
  const [isSubmittingImprovement, setIsSubmittingImprovement] = useState(false)

  const handleImprovementSubmit = async () => {
    const content = improvementContent.trim()
    if (!content) {
      alert("개선 요청 내용을 입력해주세요.")
      return
    }

    setIsSubmittingImprovement(true)
    try {
      const { data } = await apiClient.post<ProgramImprovementResponse>(
        "/api/notifications/program-improvement",
        { content }
      )
      setImprovementOpen(false)
      setImprovementContent("")
      if (data.is_sent) {
        alert("프로그램 개선 요청이 정지훈님에게 카카오 알림으로 전송되었습니다.")
        return
      }
      alert(`${data.message}${data.error ? `\n\n사유: ${data.error}` : ""}`)
    } catch (err) {
      alert(getErrorMessage(err))
    } finally {
      setIsSubmittingImprovement(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-md border bg-white p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="w-fit">
                검토위원 전용
              </Badge>
              <Badge variant="outline" className="w-fit">
                2026 OT 자료 반영
              </Badge>
            </div>
            <div className="space-y-2">
              <h1 className="text-2xl font-bold sm:text-3xl">검토위원 매뉴얼</h1>
              <p className="text-sm leading-6 text-muted-foreground sm:text-base">
                2026 모니터링 검토위원 OT 내용을 바탕으로 과업 이해, 도서 확인,
                검토서 작성, 문의, 업로드까지 실제 업무 순서대로 정리했습니다.
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row lg:shrink-0">
            <Link href="/my-reviews">
              <Button className="w-full sm:w-auto">
                <ClipboardList />
                내 검토 대상
              </Button>
            </Link>
            <Link href="/announcements">
              <Button variant="outline" className="w-full sm:w-auto">
                <Bell />
                공지사항
              </Button>
            </Link>
            <Button
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => setImprovementOpen(true)}
            >
              <MessageSquare />
              프로그램 개선 요청
            </Button>
          </div>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {taskFacts.map((fact) => (
          <Card key={fact.label}>
            <CardHeader>
              <CardDescription>{fact.label}</CardDescription>
              <CardTitle className="text-base">{fact.value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">업무 전체 흐름</h2>
          <p className="text-sm text-muted-foreground">
            최초 접속부터 검토서 제출까지 검토위원 기준의 기본 순서입니다.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {workflowSteps.map((item) => (
            <StepCard key={item.step} item={item} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">관리시스템 메뉴</h2>
          <p className="text-sm text-muted-foreground">
            접속 주소는{" "}
            <a
              href="https://moni.ksea.or.kr"
              target="_blank"
              rel="noreferrer"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              https://moni.ksea.or.kr
            </a>
            입니다.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {systemSections.map((section) => (
            <GuideCard key={section.title} section={section} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">도서 접수 후 확인</h2>
          <p className="text-sm text-muted-foreground">
            이상이 있으면 관리번호를 열어 문의를 등록하면 조별 간사에게 알림이 전송됩니다.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {reviewChecks.map((section) => (
            <GuideCard key={section.title} section={section} compact />
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4" />
              검토서 작성 유의사항
            </CardTitle>
            <CardDescription>
              xlsm 양식은 국토안전관리원 관리 양식이므로 구조를 유지해야 합니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {writingCautions.map((item) => (
                <CheckItem key={item}>{item}</CheckItem>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" />
              심각도 구분
            </CardTitle>
            <CardDescription>
              L3 또는 L4가 하나라도 있으면 재계산 대상으로 분류합니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 sm:grid-cols-2">
              {severityLevels.map((item) => (
                <div key={item.level} className={`rounded-md border p-3 ${item.tone}`}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Badge variant="outline" className="bg-white/70">
                      {item.level}
                    </Badge>
                    <span className="text-sm font-semibold">{item.name}</span>
                  </div>
                  <p className="text-sm leading-6">{item.summary}</p>
                  <p className="mt-2 text-xs font-medium">{item.action}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UploadCloud className="h-4 w-4" />
              업로드 유효성 검증
            </CardTitle>
            <CardDescription>
              미리보기와 실제 업로드에서 동일한 검증이 수행됩니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2">
              {validationGroups.map((group) => (
                <div key={group.title} className="rounded-md border bg-muted/20 p-3">
                  <h3 className="mb-2 text-sm font-semibold">{group.title}</h3>
                  <ul className="space-y-2">
                    {group.items.map((item) => (
                      <CheckItem key={item}>{item}</CheckItem>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileQuestion className="h-4 w-4" />
              문의 사용 기준
            </CardTitle>
            <CardDescription>
              문의는 간사진에게 업무 처리를 요청하는 공식 기록입니다.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <FlowRule label="간단한 문의" value="내 검토 대상 목록의 문의 버튼" />
            <Separator />
            <FlowRule label="상세한 문의" value="관리번호 클릭 후 문의사항 작성" />
            <Separator />
            <FlowRule label="간사 답변" value="카카오톡 알림과 완료 상태로 확인" />
            <Separator />
            <FlowRule label="공통 논의" value="문의가 아닌 토론방에 작성" />
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="h-4 w-4" />
              체크리스트
            </CardTitle>
            <CardDescription>
              검토서 작성 전 누락 없이 확인할 기본 항목입니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              <CheckItem>하중 적정성</CheckItem>
              <CheckItem>부재 설계 적정성</CheckItem>
              <CheckItem>구조안전 및 내진설계확인서</CheckItem>
              <CheckItem>구조도면 작성 적정성</CheckItem>
              <CheckItem>유형별 상세검토 해당 여부</CheckItem>
              <CheckItem>기타 의견과 근거 자료</CheckItem>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              부적절한 의견 작성 피하기
            </CardTitle>
            <CardDescription>
              검토 의견은 기술적 근거와 범위를 분명히 작성합니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3">
              {poorOpinionExamples.map((item) => (
                <CheckItem key={item}>{item}</CheckItem>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-xl font-semibold">돌발 상황 Q&amp;A</h2>
          <p className="text-sm text-muted-foreground">
            OT 자료의 자주 묻는 상황을 시스템 처리 기준에 맞춰 정리했습니다.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {faqs.map((faq) => (
            <Card key={faq.question}>
              <CardHeader>
                <CardTitle className="text-base">{faq.question}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-muted-foreground">{faq.answer}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Dialog
        open={improvementOpen}
        onOpenChange={(open) => {
          if (!isSubmittingImprovement) setImprovementOpen(open)
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>프로그램 개선 요청</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm leading-6 text-muted-foreground">
              매뉴얼이나 시스템 사용 중 개선이 필요한 내용을 작성하면 현재 로그인한
              카카오 계정에서 정지훈님에게 알림이 전달됩니다. 전송에는 본인 카카오
              연동과 정지훈님 친구 매칭이 필요합니다.
            </p>
            <div className="space-y-2">
              <Label htmlFor="program-improvement-content">요청 내용</Label>
              <textarea
                id="program-improvement-content"
                className="min-h-[160px] w-full resize-y rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                placeholder="예: 검토서 업로드 후 성공 메시지에 다음 단계 안내가 함께 보이면 좋겠습니다."
                value={improvementContent}
                maxLength={2000}
                disabled={isSubmittingImprovement}
                onChange={(e) => setImprovementContent(e.target.value)}
              />
              <div className="text-right text-xs text-muted-foreground">
                {improvementContent.length.toLocaleString()} / 2,000
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setImprovementOpen(false)}
              disabled={isSubmittingImprovement}
            >
              취소
            </Button>
            <Button
              onClick={handleImprovementSubmit}
              disabled={!improvementContent.trim()}
              loading={isSubmittingImprovement}
              loadingText="전송 중..."
            >
              전송
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function StepCard({ item }: { item: ManualStep }) {
  const Icon = item.icon

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <Badge variant="outline" className="h-7 w-7 justify-center rounded-full p-0">
            {item.step}
          </Badge>
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
        <CardTitle>{item.title}</CardTitle>
        <CardDescription>{item.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {item.details.map((detail) => (
            <li key={detail} className="text-sm leading-6 text-muted-foreground">
              {detail}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function GuideCard({
  section,
  compact = false,
}: {
  section: GuideSection
  compact?: boolean
}) {
  const Icon = section.icon

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 space-y-1">
            <CardTitle>{section.title}</CardTitle>
            <CardDescription>{section.description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ul className={compact ? "space-y-2" : "space-y-3"}>
          {section.items.map((item) => (
            <CheckItem key={item}>{item}</CheckItem>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function CheckItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-2 text-sm leading-6 text-muted-foreground">
      <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />
      <span>{children}</span>
    </li>
  )
}

function FlowRule({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function getErrorMessage(err: unknown): string {
  const detail = (err as ApiError).response?.data?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  if (detail && "message" in detail && typeof detail.message === "string") {
    return detail.message
  }
  return "프로그램 개선 요청 전송에 실패했습니다. 잠시 후 다시 시도해주세요."
}
