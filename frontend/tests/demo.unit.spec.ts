import { test, expect } from "@playwright/test";
import {
  demoReducer,
  initialDemoState,
  invoiceTotals,
  parseAmount,
  type DemoState,
} from "../lib/tara-demo";
import { sampleInvoicePdf } from "../lib/invoice-pdf";
import { validateEnquiry, submitDemoEnquiry } from "../lib/enquiry";
function draft(): DemoState {
  return demoReducer(demoReducer(initialDemoState, { type: "request" }), {
    type: "reply",
  });
}
test("amount parsing and illustrative VAT use integer cents with half-up rounding", () => {
  expect(parseAmount("500.01")).toBe(50001);
  expect(invoiceTotals(50000)).toEqual({
    subtotalCents: 50000,
    vatCents: 6750,
    totalCents: 56750,
  });
  expect(invoiceTotals(45000)).toEqual({
    subtotalCents: 45000,
    vatCents: 6075,
    totalCents: 51075,
  });
  expect(invoiceTotals(100)).toEqual({
    subtotalCents: 100,
    vatCents: 14,
    totalCents: 114,
  });
  for (const amount of [
    "",
    "0",
    "-10",
    "1.001",
    "1e3",
    "10000.01",
    "NaN",
    "Infinity",
    "1,000",
    "€500",
  ])
    expect(parseAmount(amount)).toBeNull();
  expect(() => invoiceTotals(1.5)).toThrow();
  expect(() => invoiceTotals(Infinity)).toThrow();
});
test("approval is tied to the current reviewed revision", () => {
  let state = draft();
  expect(demoReducer(state, { type: "approve", revision: 1 })).toEqual(state);
  state = demoReducer(state, { type: "review", revision: 1 });
  state = demoReducer(state, { type: "correct", subtotalCents: 50000 });
  expect(state.reviewedRevision).toBeNull();
  expect(state.draft.revision).toBe(2);
  expect(demoReducer(state, { type: "approve", revision: 1 })).toEqual(state);
  state = demoReducer(state, { type: "reply" });
  expect(demoReducer(state, { type: "approve", revision: 2 })).toEqual(state);
  expect(demoReducer(state, { type: "review", revision: 1 })).toEqual(state);
  state = demoReducer(state, { type: "review", revision: 2 });
  expect(demoReducer(state, { type: "approve", revision: 1 })).toEqual(state);
  state = demoReducer(state, { type: "approve", revision: 2 });
  expect(state.phase).toBe("approved");
  expect(state.messages.at(-2)?.text).toContain("€567.50");
  expect(demoReducer(state, { type: "correct", subtotalCents: 60000 })).toEqual(
    state,
  );
  expect(demoReducer(state, { type: "reset" })).toEqual(initialDemoState);
});
test("invalid corrections and repeated events cannot advance the workflow", () => {
  let state = draft();
  state = demoReducer(state, { type: "review", revision: 1 });
  for (const cents of [45000, -1, 0, 1.1, Infinity, NaN, 1000001])
    expect(
      demoReducer(state, { type: "correct", subtotalCents: cents }),
    ).toEqual(state);
  expect(demoReducer(state, { type: "request" })).toEqual(state);
  expect(demoReducer(state, { type: "reply" })).toEqual(state);
});
test("PDF contains the approved current amounts and valid byte offsets", () => {
  const pdf = sampleInvoicePdf({ subtotalCents: 50000, revision: 2 });
  expect(pdf).toContain("%PDF-1.4");
  expect(pdf).toContain("SAMPLE ONLY - NOT A TAX INVOICE");
  expect(pdf).toContain("revision 2");
  expect(pdf).toContain("EUR 500.00");
  expect(pdf).toContain("EUR 67.50");
  expect(pdf).toContain("EUR 567.50");
  expect(pdf).not.toContain("EUR 450.00");
  const xref = Number(pdf.match(/startxref\n(\d+)/)?.[1]);
  expect(pdf.slice(xref, xref + 4)).toBe("xref");
  const offsets = Array.from(pdf.matchAll(/(\d{10}) 00000 n/g)).map((m) =>
    Number(m[1]),
  );
  offsets.forEach((offset, i) =>
    expect(pdf.slice(offset, offset + 7)).toBe(`${i + 1} 0 obj`),
  );
  expect(new TextEncoder().encode(pdf).length).toBe(pdf.length);
});
test("enquiry validation requires consent and the mock adapter never reports persistence", async () => {
  const valid = {
    name: "Alex Example",
    email: "demo@example.com",
    trade: "Plumber",
    consent: true,
  };
  expect(validateEnquiry(valid)).toEqual({});
  expect(validateEnquiry({ ...valid, consent: false })).toHaveProperty(
    "consent",
  );
  expect(validateEnquiry({ ...valid, email: "invalid" })).toHaveProperty(
    "email",
  );
  expect(validateEnquiry({ ...valid, phone: "letters" })).toHaveProperty(
    "phone",
  );
  expect(validateEnquiry({ ...valid, phone: "+353 00 000 0000" })).toEqual({});
  expect(validateEnquiry(valid, true)).toHaveProperty("message");
  expect(await submitDemoEnquiry(valid)).toEqual({
    mode: "demo",
    persisted: false,
  });
});
