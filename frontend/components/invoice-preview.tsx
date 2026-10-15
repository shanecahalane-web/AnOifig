import {
  DEMO_DATE,
  DEMO_DUE_DATE,
  DEMO_INVOICE_NUMBER,
  euros,
  invoiceTotals,
  type InvoiceDraft,
} from "@/lib/tara-demo";
export default function InvoicePreview({
  draft,
  approved,
}: {
  draft: InvoiceDraft;
  approved: boolean;
}) {
  const totals = invoiceTotals(draft.subtotalCents);
  return (
    <article
      className="invoice-paper"
      aria-label={`Sample invoice version ${draft.revision}`}
    >
      <div className="document-disclaimer">
        SAMPLE ONLY · NOT A TAX INVOICE · DO NOT PAY
      </div>
      <div className="document-top">
        <div>
          <span className="document-kicker">FICTIONAL BUSINESS</span>
          <h3>O’Neill Plumbing</h3>
          <p>
            1 Example Lane, Demo Town, Ireland
            <br />
            demo@plumbing.example
            <br />
            Phone: not a live number
            <br />
            VAT reference: DEMO-NOT-VALID
          </p>
        </div>
        <div className="document-title">
          <span>INVOICE</span>
          <strong>{DEMO_INVOICE_NUMBER}</strong>
          <span className="document-state">
            {approved ? "Approved sample" : "Draft for review"} · v
            {draft.revision}
          </span>
        </div>
      </div>
      <div className="document-parties">
        <div>
          <span className="document-kicker">BILL TO · FICTIONAL CUSTOMER</span>
          <strong>John Murphy</strong>
          <p>
            2 Sample Road
            <br />
            Demo Town, Ireland
          </p>
        </div>
        <dl>
          <div>
            <dt>Invoice date</dt>
            <dd>{DEMO_DATE}</dd>
          </div>
          <div>
            <dt>Payment due</dt>
            <dd>{DEMO_DUE_DATE}</dd>
          </div>
          <div>
            <dt>Currency</dt>
            <dd>EUR</dd>
          </div>
        </dl>
      </div>
      <table>
        <caption className="sr-only">Sample invoice charges</caption>
        <thead>
          <tr>
            <th scope="col">Description</th>
            <th scope="col">Qty</th>
            <th scope="col">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              Shower replacement<small>Supply and labour · demonstration</small>
            </td>
            <td>1</td>
            <td>{euros(totals.subtotalCents)}</td>
          </tr>
        </tbody>
      </table>
      <dl className="document-totals">
        <div>
          <dt>Subtotal</dt>
          <dd>{euros(totals.subtotalCents)}</dd>
        </div>
        <div>
          <dt>Illustrative VAT · 13.5%</dt>
          <dd>{euros(totals.vatCents)}</dd>
        </div>
        <div className="document-total">
          <dt>Sample total</dt>
          <dd>{euros(totals.totalCents)}</dd>
        </div>
      </dl>
      <div className="document-payment">
        <span className="document-kicker">FICTIONAL PAYMENT DETAILS</span>
        <p>
          Account: DEMO-ACCOUNT
          <br />
          IBAN: DEMO-INVALID · Not a bank account
          <br />
          Reference: {DEMO_INVOICE_NUMBER}
        </p>
      </div>
      <p className="document-note">
        All details are fictional. The 13.5% VAT rate is an assumption for this
        demonstration, not tax advice. Actual treatment depends on the business
        and work. No invoice is issued or delivered.
      </p>
    </article>
  );
}
