"use client"

import { useQueries } from "@tanstack/react-query"
import { ArrowRight, Bot, CalendarDays, Loader2, MapPin } from "lucide-react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import type { EventPublic, PopupPublic } from "@/client"
import { Button } from "@/components/ui/button"
import useAgent from "@/hooks/useAgent"
import useAuth from "@/hooks/useAuth"
import { pendingSetupStep } from "@/lib/agentService"
import { useCityProvider } from "@/providers/cityProvider"
import { fetchAllPortalEvents } from "./[popupSlug]/events/lib/fetchAllPortalEvents"

/** Home: what needs the participant's attention today. */
export default function DashboardPage() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const { getPopups, popupsLoaded } = useCityProvider()
  const popups = getPopups()
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const end = new Date(start)
  end.setDate(end.getDate() + 1)
  const day = start.toISOString()

  const results = useQueries({
    queries: popups.map((popup) => ({
      queryKey: ["dashboard", "rsvps", popup.id, day],
      queryFn: () =>
        fetchAllPortalEvents({
          popupId: popup.id,
          rsvpedOnly: true,
          startAfter: day,
          startBefore: end.toISOString(),
        }),
      staleTime: 60_000,
    })),
  })
  const loading = !popupsLoaded || results.some((r) => r.isLoading)
  const today: { event: EventPublic; popup: PopupPublic }[] = results
    .flatMap((r, i) =>
      (r.data ?? []).map((event) => ({ event, popup: popups[i] })),
    )
    .sort((a, b) => a.event.start_time.localeCompare(b.event.start_time))

  const hour = new Date().getHours()
  const greeting =
    hour < 12
      ? t("dashboard.morning")
      : hour < 18
        ? t("dashboard.afternoon")
        : t("dashboard.evening")
  const time = new Intl.DateTimeFormat(i18n.language, {
    hour: "numeric",
    minute: "2-digit",
  })

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-6 sm:px-8 sm:py-10">
      <header>
        <p className="text-sm text-muted-foreground">
          {new Intl.DateTimeFormat(i18n.language, {
            weekday: "long",
            month: "long",
            day: "numeric",
          }).format(new Date())}
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight sm:text-4xl">
          {greeting}
          {user?.first_name ? `, ${user.first_name}` : ""}
        </h1>
      </header>

      <AgentPrompt />

      <section aria-labelledby="today" className="rounded-2xl border bg-card">
        <div className="flex items-center gap-3 border-b px-5 py-4 sm:px-6">
          <CalendarDays className="size-5 text-primary" aria-hidden="true" />
          <h2 id="today" className="font-semibold">
            {t("dashboard.today_title")}
          </h2>
        </div>
        {loading ? (
          <div role="status" className="flex justify-center py-10">
            <Loader2
              className="size-5 animate-spin text-muted-foreground"
              aria-label={t("dashboard.loading")}
            />
          </div>
        ) : today.length === 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-6 sm:px-6">
            <p className="text-sm text-muted-foreground">
              {t("dashboard.today_empty")}
            </p>
            {popups[0] && (
              <Button asChild variant="outline" size="sm">
                <Link href={`/portal/${popups[0].slug}/events`}>
                  {t("dashboard.browse_events")}
                </Link>
              </Button>
            )}
          </div>
        ) : (
          <ul className="divide-y">
            {today.map(({ event, popup }) => (
              <li key={`${event.id}:${event.start_time}`}>
                <Link
                  href={`/portal/${popup.slug}/events/${event.id}`}
                  className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-muted/40 sm:px-6"
                >
                  <span className="w-16 shrink-0 text-sm font-medium tabular-nums">
                    {time.format(new Date(event.start_time))}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">
                      {event.title}
                    </span>
                    {(event.venue_title || event.custom_location_name) && (
                      <span className="mt-0.5 flex items-center gap-1 text-sm text-muted-foreground">
                        <MapPin className="size-3.5" aria-hidden="true" />
                        {event.venue_title || event.custom_location_name}
                      </span>
                    )}
                  </span>
                  <ArrowRight
                    className="size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/** Shown until the participant's agent is set up. */
function AgentPrompt() {
  const { t } = useTranslation()
  const { state } = useAgent()
  const step = state ? pendingSetupStep(state) : null
  if (!step) return null
  const started = step !== "intro"
  return (
    <section className="flex flex-col gap-5 rounded-2xl border border-primary/30 bg-primary/5 p-5 sm:flex-row sm:items-center sm:p-6">
      <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
        <Bot className="size-6" aria-hidden="true" />
      </span>
      <div className="flex-1">
        <h2 className="text-lg font-semibold">
          {started
            ? t("dashboard.agent_continue_title")
            : t("dashboard.agent_title")}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("dashboard.agent_body")}
        </p>
      </div>
      <Button asChild size="lg" className="shrink-0">
        <Link href="/portal/agent">
          {started ? t("dashboard.agent_continue") : t("dashboard.agent_cta")}
          <ArrowRight className="ml-2 size-4" aria-hidden="true" />
        </Link>
      </Button>
    </section>
  )
}
