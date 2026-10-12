import { useQueries } from "@tanstack/react-query"
import { ArrowRight, QrCode } from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { TicketingStepsService } from "@/client"
import { imageOptimization } from "@/lib/image-optimization"
import type { OtherPurchasedProduct } from "../otherProductsProjection"
import { resolveOtherProductVisual } from "../otherProductVisual"
import QRcode from "./common/QRcode"

export function OtherPurchasedProducts({
  products,
  paymentsHref,
  popupId,
  catalog = [],
}: {
  products: OtherPurchasedProduct[]
  paymentsHref: string
  /** Scopes the step lookup that picks each product's icon. */
  popupId?: string
  /** Products the portal already loaded, for their images. */
  catalog?: Array<{ id: string; image_url?: string | null }>
}) {
  const { t } = useTranslation()
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null)
  // Resolve the selection from current data, so a unit revoked on refetch
  // also closes its QR.
  const activeProduct = products.find((product) =>
    product.scannableUnits.some((unit) => unit.id === selectedUnitId),
  )
  const activeUnitIndex =
    activeProduct?.scannableUnits.findIndex(
      (unit) => unit.id === selectedUnitId,
    ) ?? -1
  const activeUnit = activeProduct?.scannableUnits[activeUnitIndex]
  const flowIds = [...new Set(products.map((product) => product.salesFlowId))]
  // Same key as the checkout's own step query, so a buyer who just paid
  // reads these from cache.
  const stepQueries = useQueries({
    queries: flowIds.map((salesFlowId) => ({
      queryKey: ["ticketing-steps-portal", popupId ?? null, salesFlowId],
      queryFn: () =>
        TicketingStepsService.listPortalTicketingSteps({
          popupId: popupId!,
          salesFlowId,
        }),
      enabled: !!popupId,
    })),
  })
  const stepsByFlow = new Map(
    flowIds.map((flowId, index) => [
      flowId,
      stepQueries[index]?.data?.results ?? [],
    ]),
  )

  if (products.length === 0) return null

  return (
    <section aria-labelledby="other-products-title" className="space-y-4">
      <div>
        <h2
          id="other-products-title"
          className="text-lg font-semibold text-pass-title"
        >
          {t("passes.other_products")}
        </h2>
        <p className="mt-1 text-sm text-pass-text">
          {t("passes.other_products_description")}
        </p>
      </div>

      <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
        {products.map((product) => {
          const { imageUrl, Icon } = resolveOtherProductVisual(
            product,
            stepsByFlow.get(product.salesFlowId) ?? [],
            catalog,
          )
          return (
            <li
              key={product.id}
              className="flex items-center justify-between gap-4 p-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                {imageUrl ? (
                  <Image
                    src={imageUrl}
                    alt=""
                    width={36}
                    height={36}
                    className="size-9 shrink-0 rounded-full bg-muted object-cover"
                    {...imageOptimization(imageUrl)}
                  />
                ) : (
                  <div className="grid size-9 shrink-0 place-items-center rounded-full bg-muted">
                    <Icon className="size-4 text-muted-foreground" />
                  </div>
                )}
                <p className="truncate font-medium text-pass-title">
                  {product.name}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {product.scannableUnits.length > 0 && (
                  <div className="flex flex-wrap justify-end gap-2">
                    {product.scannableUnits.map((unit, index) => (
                      <button
                        key={unit.id}
                        type="button"
                        onClick={() => setSelectedUnitId(unit.id)}
                        aria-label={t("orders.show_unit_qr_label", {
                          product: product.name,
                          number: index + 1,
                        })}
                        className="cursor-pointer text-pass-text transition-colors hover:text-pass-title"
                      >
                        <QrCode className="size-5" />
                      </button>
                    ))}
                  </div>
                )}
                <span className="text-sm font-medium text-pass-text">
                  × {product.quantity}
                </span>
              </div>
            </li>
          )
        })}
      </ul>

      <Link
        href={paymentsHref}
        className="inline-flex items-center gap-2 text-sm font-semibold text-pass-title hover:underline"
      >
        {t("passes.view_payment_details")}
        <ArrowRight className="size-4" />
      </Link>

      <QRcode
        check_in_code={activeUnit?.checkInCode ?? ""}
        isOpen={activeUnit != null}
        onOpenChange={(open) => {
          if (!open) setSelectedUnitId(null)
        }}
        title={t("orders.unit_qr_title", {
          product: activeProduct?.name,
          number: activeUnitIndex + 1,
        })}
        description={t("orders.unit_qr_description")}
      />
    </section>
  )
}
