import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import en from "@/i18n/locales/en.json"
import type { OtherPurchasedProduct } from "../otherProductsProjection"
import { OtherPurchasedProducts } from "./OtherPurchasedProducts"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options: Record<string, unknown> = {}) => {
      const label =
        en.orders[key.replace("orders.", "") as keyof typeof en.orders]
      return String(label ?? key).replace(/{{(\w+)}}/g, (_, name) =>
        String(options[name] ?? ""),
      )
    },
    i18n: { language: "en" },
  }),
}))

vi.mock("@/client", () => ({
  TicketingStepsService: {
    listPortalTicketingSteps: vi.fn(async () => ({ results: [] })),
  },
}))

// Exercise the real shared dialog and verify the exact scanner payload.
vi.mock("react-qr-code", () => ({
  default: ({ value }: { value: string }) => (
    <div data-testid="qr-payload">{value}</div>
  ),
}))

vi.mock("@/lib/qr-download", () => ({
  downloadQrPng: vi.fn(async () => {}),
}))

const product = (
  overrides: Partial<OtherPurchasedProduct> = {},
): OtherPurchasedProduct => ({
  id: "shirt",
  name: "Conference T-Shirt",
  quantity: 2,
  category: "merch",
  salesFlowId: "merch-flow",
  scannableUnits: [
    { id: "unit-1", checkInCode: "SHIRT1" },
    { id: "unit-2", checkInCode: "SHIRT2" },
  ],
  ...overrides,
})

function renderProducts(products: OtherPurchasedProduct[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return render(
    <OtherPurchasedProducts
      products={products}
      paymentsHref="/portal/demo/orders"
    />,
    { wrapper },
  )
}

afterEach(cleanup)

describe("OtherPurchasedProducts QR", () => {
  it("opens each unit's own QR", () => {
    renderProducts([product()])

    const buttons = screen.getAllByRole("button", { name: /View QR for/ })
    expect(buttons).toHaveLength(2)

    fireEvent.click(
      screen.getByRole("button", {
        name: "View QR for Conference T-Shirt, unit 2",
      }),
    )

    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("Conference T-Shirt · QR 2")).toBeTruthy()
    expect(within(dialog).getByTestId("qr-payload").textContent).toBe(
      JSON.stringify({ code: "SHIRT2" }),
    )
  })

  it("shows no QR for products without scannable units", () => {
    renderProducts([product({ name: "testlunch", scannableUnits: [] })])

    expect(screen.getByText("testlunch")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /View QR for/ })).toBeNull()
  })

  it("closes the QR when its unit disappears on refetch", () => {
    const { rerender } = renderProducts([product()])
    fireEvent.click(
      screen.getByRole("button", {
        name: "View QR for Conference T-Shirt, unit 1",
      }),
    )
    expect(screen.getByRole("dialog")).toBeTruthy()

    rerender(
      <OtherPurchasedProducts
        products={[product({ scannableUnits: [] })]}
        paymentsHref="/portal/demo/orders"
      />,
    )

    expect(screen.queryByRole("dialog")).toBeNull()
  })
})
