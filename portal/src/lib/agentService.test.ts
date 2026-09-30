import { describe, expect, it } from "vitest"
import { agentError, publicBotUrl } from "./agentService"

describe("public Telegram links", () => {
  it("builds a public username link without accepting a token, URL or query payload", () => {
    expect(publicBotUrl("village_companion_bot")).toBe(
      "https://t.me/village_companion_bot",
    )
    for (const value of [
      null,
      "",
      "https://evil.test",
      "123456:secret_token",
      "mybot?start=capability",
      "mybot#secret",
      "mybot/secret",
    ]) {
      expect(publicBotUrl(value)).toBeNull()
    }
  })
})

describe("agent error disclosure", () => {
  it("retains backend diagnostics while removing credentials", () => {
    const result = agentError({
      body: {
        detail:
          "Could not attach 123456789:abcdefghijklmnopqrstuvwxyz_123456789 using Bearer private-session: gateway unavailable",
      },
    })
    expect(result).toContain("gateway unavailable")
    expect(result).not.toContain("abcdefghijklmnopqrstuvwxyz")
    expect(result).not.toContain("private-session")
  })
  it("handles non-error rejection values without trusting their shape", () => {
    expect(agentError(null)).toContain("Try again")
    expect(agentError({ body: { detail: 123 } })).toContain("Try again")
    expect(agentError(new Error("Runtime unavailable"))).toBe(
      "Runtime unavailable",
    )
  })
})
