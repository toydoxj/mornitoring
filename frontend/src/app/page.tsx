"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/stores/authStore"

export default function Home() {
  const router = useRouter()
  const { user, isLoading, fetchMe } = useAuthStore()

  useEffect(() => {
    fetchMe()
  }, [fetchMe])

  useEffect(() => {
    if (isLoading) return
    if (!user) {
      router.push("/login")
    } else if (user.role === "reviewer") {
      router.push("/my-reviews")
    } else {
      router.push("/buildings")
    }
  }, [user, isLoading, router])

  return null
}
