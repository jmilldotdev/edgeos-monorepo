"use client"

import { notFound } from "next/navigation"
import { useEffect, useState } from "react"

/**
 * Development-only sign-in for personas minted by
 * `backend: uv run python -m app.dev.persona`. The token arrives in the URL
 * fragment so it never reaches server logs.
 */
export default function DevLoginPage() {
  if (process.env.NODE_ENV !== "development") notFound()
  return <DevLogin />
}

function DevLogin() {
  const [error, setError] = useState("")
  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get(
      "token",
    )
    if (!token) {
      setError("Missing #token=… in the URL.")
      return
    }
    localStorage.setItem("token", token)
    window.location.replace("/portal")
  }, [])
  return (
    <p className="p-8 text-sm text-muted-foreground">
      {error || "Signing in…"}
    </p>
  )
}
