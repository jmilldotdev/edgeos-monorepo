"use client"

import { ChevronDown } from "lucide-react"
import { useState } from "react"
import { Checkbox } from "@/components/ui/checkbox"
import { CONSENT_BRIEF } from "@/lib/agentService"
import { cn } from "@/lib/utils"

const FACTS = [
  {
    term: "What’s studied",
    detail:
      "Your setup answers, the introductions and plans your agent proposes and whether you accept them, agent-to-agent negotiations, how often you use it, and short surveys.",
  },
  {
    term: "Who you are",
    detail:
      "Replaced with a study ID before analysis. Published findings never identify you.",
  },
  {
    term: "Private chats",
    detail: "Never published. Opened only to fix problems.",
  },
  {
    term: "Changing your mind",
    detail:
      "Change or withdraw anytime from About you. Your agent and your ticket are unaffected.",
  },
]

export default function ConsentChoices({
  research,
  training,
  onResearch,
  onTraining,
}: {
  research: boolean
  training: boolean
  onResearch: (value: boolean) => void
  onTraining: (value: boolean) => void
}) {
  const [showTerms, setShowTerms] = useState(false)
  return (
    <div className="space-y-6">
      <dl className="divide-y rounded-xl border bg-card">
        {FACTS.map((fact) => (
          <div
            key={fact.term}
            className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4"
          >
            <dt className="text-sm font-medium">{fact.term}</dt>
            <dd className="text-sm text-muted-foreground">{fact.detail}</dd>
          </div>
        ))}
      </dl>
      <div>
        <button
          type="button"
          aria-expanded={showTerms}
          onClick={() => setShowTerms(!showTerms)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronDown
            className={cn(
              "size-4 transition-transform",
              showTerms && "rotate-180",
            )}
            aria-hidden="true"
          />
          Full research terms (draft)
        </button>
        {showTerms && (
          <div className="mt-3 space-y-3 text-sm leading-6 text-muted-foreground">
            <p>
              Agent Village studies whether personal agents represent people
              accurately and help a community coordinate. Edge City Research
              runs the study with academic partners; study groups are still
              being finalized.
            </p>
            <p>
              Use is limited to research associated with Edge City events.
              In-person research sessions ask for consent again. Automatic
              introductions and offer allocation are not switched on by this
              setup.
            </p>
            <p className="text-xs">Consent version {CONSENT_BRIEF}</p>
          </div>
        )}
      </div>
      <div className="space-y-3">
        <Choice
          checked={research}
          onChange={onResearch}
          title="Take part in the Agent Village research"
          tag="Required for an agent"
        >
          My setup context and agent activity may be used for the research
          described above. I understand this is experimental software, not a
          confidential or safety-critical service.
        </Choice>
        <Choice
          checked={training}
          onChange={onTraining}
          title="Also allow model training"
          tag="Optional"
        >
          My de-identified agent activity may be used to train future AI models.
        </Choice>
      </div>
    </div>
  )
}

function Choice({
  checked,
  onChange,
  title,
  tag,
  children,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  title: string
  tag: string
  children: React.ReactNode
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-xl border p-4 transition-colors",
        checked ? "border-primary bg-primary/5" : "bg-card hover:bg-muted/40",
      )}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
        className="mt-0.5"
      />
      <span className="space-y-1">
        <span className="flex flex-wrap items-center gap-2 font-medium">
          {title}
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">
            {tag}
          </span>
        </span>
        <span className="block text-sm text-muted-foreground">{children}</span>
      </span>
    </label>
  )
}
