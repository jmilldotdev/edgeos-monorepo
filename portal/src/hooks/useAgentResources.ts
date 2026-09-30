import {
  Bot,
  LayoutDashboard,
  NotebookPen,
  Radio,
  ShieldCheck,
} from "lucide-react"
import { useTranslation } from "react-i18next"
import useAgent from "@/hooks/useAgent"
import { pendingSetupStep } from "@/lib/agentService"
import type { Resource } from "@/types/resources"

/**
 * Sidebar entries that do not depend on the selected popup: the dashboard,
 * and the Agents section, which mirrors whether setup is finished.
 */
export default function useAgentResources(): Resource[] {
  const { t } = useTranslation()
  const { state } = useAgent()
  const dashboard: Resource = {
    name: t("sidebar.dashboard"),
    icon: LayoutDashboard,
    status: "active",
    path: "/portal",
    group: "home",
  }
  if (!state) return [dashboard]
  const step = pendingSetupStep(state)
  if (step)
    return [
      dashboard,
      {
        name: t("sidebar.agent_setup"),
        icon: Bot,
        status: "active",
        path: "/portal/agent",
        group: "agents",
        value:
          step === "intro"
            ? t("sidebar.agent_new")
            : t("sidebar.agent_in_progress"),
      },
    ]
  return [
    dashboard,
    ...(
      [
        [t("sidebar.agent_overview"), Bot, "/portal/agent"],
        [t("sidebar.agent_about"), NotebookPen, "/portal/agent/context"],
        [t("sidebar.agent_connections"), Radio, "/portal/agent/connections"],
        [t("sidebar.agent_privacy"), ShieldCheck, "/portal/agent/privacy"],
      ] as const
    ).map(
      ([name, icon, path]): Resource => ({
        name,
        icon,
        status: "active",
        path,
        group: "agents",
      }),
    ),
  ]
}
