import {
  DEMO_DATE,
  DEMO_DUE_DATE,
  DEMO_INVOICE_NUMBER,
  invoiceTotals,
  type InvoiceDraft,
} from "./tara-demo";
/** A small, uncompressed one-page PDF. ASCII keeps byte offsets deterministic. */
export function sampleInvoicePdf(draft: InvoiceDraft): string {
  const t = invoiceTotals(draft.subtotalCents);
  const money = (c: number) => `EUR ${(c / 100).toFixed(2)}`;
  const lines = [
    ["SAMPLE ONLY - NOT A TAX INVOICE", 18],
    ["Approval simulated. Not issued, sent or payable.", 10],
    ["", 10],
    ["O'Neill Plumbing - FICTIONAL BUSINESS", 18],
    ["1 Example Lane, Demo Town, Ireland", 11],
    ["demo@plumbing.example | Phone: not a live number", 10],
    ["VAT reference: DEMO-NOT-VALID", 10],
    ["", 12],
    [`Sample invoice: ${DEMO_INVOICE_NUMBER} / revision ${draft.revision}`, 12],
    [`Date: ${DEMO_DATE} | Due: ${DEMO_DUE_DATE}`, 10],
    ["", 12],
    ["BILL TO", 10],
    ["John Murphy - FICTIONAL CUSTOMER", 12],
    ["2 Sample Road, Demo Town, Ireland", 10],
    ["", 12],
    ["WORK                                  QTY       AMOUNT", 11],
    [
      `Shower replacement (supply & labour)    1         ${money(t.subtotalCents)}`,
      10,
    ],
    ["", 12],
    [
      `Subtotal                                        ${money(t.subtotalCents)}`,
      11,
    ],
    [
      `Illustrative VAT (13.5%)                          ${money(t.vatCents)}`,
      11,
    ],
    [
      `Sample total                                    ${money(t.totalCents)}`,
      16,
    ],
    ["", 12],
    ["PAYMENT DETAILS - FICTIONAL / DO NOT PAY", 11],
    ["Account: DEMO-ACCOUNT | IBAN: DEMO-INVALID", 10],
    [`Reference: ${DEMO_INVOICE_NUMBER}`, 10],
    ["", 12],
    ["13.5% VAT is an assumed demo rate, not tax advice.", 10],
    ["Actual VAT treatment depends on the business and work.", 10],
    ["All names, addresses and amounts are demonstration data.", 10],
  ] as const;
  let y = 785;
  const commands =
    "q 0.96 0.93 0.85 rg 35 744 525 64 re f Q\n0.07 0.18 0.14 rg\n" +
    lines
      .map(([line, size]) => {
        const command = `BT /F1 ${size} Tf 45 ${y} Td (${line.replace(/[\\()]/g, "\\$&")}) Tj ET`;
        y -= size + 9;
        return command;
      })
      .join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${commands.length} >>\nstream\n${commands}\nendstream`,
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((obj, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${obj}\nendobj\n`;
  });
  const start = pdf.length;
  pdf +=
    `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` +
    offsets
      .slice(1)
      .map((n) => `${String(n).padStart(10, "0")} 00000 n \n`)
      .join("") +
    `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return pdf;
}
export function downloadSampleInvoice(draft: InvoiceDraft) {
  const url = URL.createObjectURL(
    new Blob([sampleInvoicePdf(draft)], { type: "application/pdf" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `an-oifig-SAMPLE-v${draft.revision}.pdf`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
