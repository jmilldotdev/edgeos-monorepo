import "@/lib/api-client"
import { OpenAPI } from "@/client"
import { request } from "@/client/core/request"

export type AgentDraft = {
  profile: {
    name: string
    whatYouDo: string
    basedIn: string
    staying: string
    links: string
  }
  sources: {
    id: string
    method: "ai" | "write" | "voice"
    label: string
    text: string
    words: number
  }[]
  intentions: {
    id: string
    category: "build" | "learn" | "meet" | "explore"
    text: string
    why: string
    kept: boolean
    addedByYou: boolean
  }[]
  intentionsConfirmed: boolean
  answers: Record<string, string[]>
  offers: { id: string; title: string; detail: string }[]
  agentsDecideOffers: boolean
  questionsDone: boolean
  extractionSourceHash?: string
}
export type AgentExtraction = {
  intentions: Pick<
    AgentDraft["intentions"][number],
    "category" | "text" | "why"
  >[]
  offers: Pick<AgentDraft["offers"][number], "title" | "detail">[]
}
export type AgentState = {
  revision: number
  draft: AgentDraft
  consent: {
    research: boolean
    training: boolean
    briefVersion: string
    acceptedAt: string | null
  }
  agent: null | {
    id: string
    status: "creating" | "ready" | "failed"
    provider: string
    dashboardUrl: string | null
    chatUrl: string | null
    error: string | null
    telegramSupported: boolean
  }
  contextPending: boolean
  hostError: string | null
  telegramPairingId: string | null
}
export type TelegramState = {
  supported: boolean
  attached: boolean
  ready: boolean
  state: string
  botUsername: string | null
  botUrl: string | null
  approvedUserIds: string[]
  pending: {
    code: string
    platform: "telegram"
    userId: string
    userName: string
    expiresAt: string | null
    ageMinutes: number | null
  }[]
}
export type DesktopAttempt = {
  id: string
  status:
    | "pending"
    | "opened"
    | "connected"
    | "failed"
    | "incompatible"
    | "cancelled"
    | "expired"
  expiresAt: string
  updatedAt: string
  code: string | null
  desktopVersion: string | null
}
export type TelegramSetupStart = {
  pairing_id: string
  suggested_username: string
  deep_link: string
  qr_payload: string
  expires_at: string
}
export type TelegramSetupState = {
  status: "waiting" | "ready" | "applied"
  bot_username?: string
  owner_user_id?: string
  expires_at: string
  deep_link?: string
  qr_payload?: string
}
function call<T>(
  method: "GET" | "PUT" | "POST" | "DELETE",
  path = "",
  body?: unknown,
) {
  const options = {
    method,
    url: `/api/v1/agent${path}`,
    body,
    mediaType: "application/json",
  }
  return request<T>(OpenAPI, options)
}
export const AgentService = {
  get: () => call<AgentState>("GET"),
  reset: (revision: number) =>
    call<AgentState>("POST", "/reset", { revision, confirmed: true }),
  save: (revision: number, draft: AgentDraft) =>
    call<AgentState>("PUT", "", { revision, draft }),
  extract: (draft: AgentDraft) =>
    call<AgentExtraction>("POST", "/extract", { draft }),
  consent: (
    revision: number,
    research: boolean,
    training: boolean,
    briefVersion: string,
  ) =>
    call<AgentState>("PUT", "/consent", {
      revision,
      research,
      training,
      briefVersion,
    }),
  provision: (revision: number) =>
    call<AgentState>("POST", "/provision", { revision }),
  sync: (revision: number) => call<AgentState>("POST", "/sync", { revision }),
  desktop: () => call<{ attempt: DesktopAttempt | null }>("GET", "/desktop"),
  connectDesktop: () =>
    call<{ attempt: DesktopAttempt; deepLink: string }>("POST", "/desktop", {}),
  telegram: () => call<TelegramState>("GET", "/telegram"),
  telegramAction: (
    body:
      | { action: "attach"; token: string }
      | { action: "approve"; code: string; userId: string; confirmed: true }
      | { action: "revoke"; userId: string; confirmed: true },
  ) => call<{ accepted: true }>("POST", "/telegram", body),
  startTelegramSetup: () =>
    call<TelegramSetupStart>("POST", "/telegram/onboarding/start", {}),
  telegramSetup: (id: string) =>
    call<TelegramSetupState>(
      "GET",
      `/telegram/onboarding/${encodeURIComponent(id)}`,
    ),
  applyTelegramSetup: (id: string, ownerUserId: string) =>
    call<{ ok: true; telegramUserId: string; bot_username: string }>(
      "POST",
      `/telegram/onboarding/${encodeURIComponent(id)}/apply`,
      { owner_user_id: ownerUserId, confirmed: true },
    ),
  cancelTelegramSetup: (id: string) =>
    call<{ ok: true }>(
      "DELETE",
      `/telegram/onboarding/${encodeURIComponent(id)}`,
    ),
}

/** Never render secrets accidentally included in an upstream error. */
export function agentError(error: unknown): string {
  let message = "The request could not be completed. Try again."
  if (error && typeof error === "object") {
    if ("message" in error && typeof error.message === "string")
      message = error.message
    if (
      "body" in error &&
      error.body &&
      typeof error.body === "object" &&
      "detail" in error.body &&
      typeof error.body.detail === "string"
    )
      message = error.body.detail
  }
  return message
    .replace(/\b\d{5,}:[A-Za-z0-9_-]{20,}\b/g, "[bot token redacted]")
    .replace(/Bearer\s+\S+/gi, "Bearer [redacted]")
}
export function publicBotUrl(username: string | null): string | null {
  return username && /^[A-Za-z0-9_]{5,32}$/.test(username)
    ? `https://t.me/${username}`
    : null
}

/** Consent brief recorded with every choice; bump when the terms change. */
export const CONSENT_BRIEF = "av2-consent-draft-2026-09-24"

/** Draft source id for the optional free-form "anything else" block. */
export const EXTRA_CONTEXT_ID = "portal-context"

export type SetupStep = "intro" | "consent" | "about"

export function hasContext(draft: AgentDraft): boolean {
  return draft.profile.whatYouDo.trim().length > 0
}

/**
 * The onboarding step a participant still has to finish, or null once they
 * have consented, described themselves and have an agent. Derived only from
 * server state so every device agrees.
 */
export function pendingSetupStep(state: AgentState): SetupStep | null {
  if (!state.consent.acceptedAt)
    return hasContext(state.draft) || state.agent ? "consent" : "intro"
  if (!state.consent.research) return "consent"
  if (!state.agent || !hasContext(state.draft)) return "about"
  return null
}

export function extraContext(draft: AgentDraft): string {
  return draft.sources.find((s) => s.id === EXTRA_CONTEXT_ID)?.text ?? ""
}

export function withExtraContext(draft: AgentDraft, text: string): AgentDraft {
  const words = wordCount(text)
  return {
    ...draft,
    sources: [
      ...draft.sources.filter((s) => s.id !== EXTRA_CONTEXT_ID),
      ...(words
        ? [
            {
              id: EXTRA_CONTEXT_ID,
              method: "write" as const,
              label: "Personal context",
              text,
              words,
            },
          ]
        : []),
    ],
  }
}

export function wordCount(text: string): number {
  const trimmed = text.trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}
