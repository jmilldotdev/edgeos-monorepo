import { Bot, LayoutDashboard, NotebookPen, Radio } from "lucide-react"
import { useTranslation } from "react-i18next"
import type { Resource } from "@/types/resources"

/**
 * Sidebar entries that do not depend on the selected popup: the dashboard and
 * the Agents section. The nav is fixed; each agent page shows setup until the
 * participant has finished it.
 */
export default function useAgentResources(): Resource[] {
  const { t } = useTranslation()
  return (
    [
      [t("sidebar.dashboard"), LayoutDashboard, "/portal", "home"],
      [t("sidebar.agent_overview"), Bot, "/portal/agent", "agents"],
      [
        t("sidebar.agent_about"),
        NotebookPen,
        "/portal/agent/context",
        "agents",
      ],
      [
        t("sidebar.agent_connections"),
        Radio,
        "/portal/agent/connections",
        "agents",
      ],
    ] as const
  ).map(([name, icon, path, group]) => ({
    name,
    icon,
    status: "active",
    path,
    group,
  }))
}
