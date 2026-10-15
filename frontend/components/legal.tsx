import Link from "next/link";
export default function Legal({ terms = false }: { terms?: boolean }) {
  return (
    <main id="main" className="section inner-page legal">
      <div className="eyebrow">TRANSPARENCY FIRST</div>
      <h1>
        {terms ? "Terms of use" : "Privacy notice"}
        <em> — draft.</em>
      </h1>
      <div className="form-notice">
        <strong>DRAFT — REQUIRES LEGAL REVIEW. Not a final policy.</strong>
        <p>
          Qualified Irish legal counsel must review and complete this document
          before launch or personal data collection.
        </p>
      </div>
      {terms ? (
        <>
          <h2>About this preview</h2>
          <p>
            An Oifig is developing Tara for tradespeople. This is an
            informational prototype. No live WhatsApp assistant, payment
            service, invoice issuance or customer dashboard is provided.
          </p>
          <h2>Demonstration and pricing</h2>
          <p>
            Demonstration names, messages and documents are fictional. They are
            not invoices, tax calculations or accounting advice. Pricing,
            availability and planned features are unconfirmed, not an offer.
          </p>
          <h2>Your control</h2>
          <p>
            Approval is simulated in browser memory only. Forms download a local
            file; they do not submit information, create an account or establish
            a contract.
          </p>
          <h2>Before publication</h2>
          <p>
            Legal review must establish the operator’s identity and address,
            contact method, acceptable use, intellectual property provisions,
            consumer rights, warranties, proportionate liability provisions,
            disputes, governing law and future subscription and cancellation
            conditions. These matters remain unresolved.
          </p>
        </>
      ) : (
        <>
          <h2>Information in this preview</h2>
          <p>
            The demonstration uses fictional data in your browser. Form details
            are held in the current page and used only to create a file you
            download. No submission, registration, analytics or advertising
            service is connected by this application.
          </p>
          <h2>Local files and hosting</h2>
          <p>
            Downloaded files contain what you enter. Keep or delete these files
            as you would any personal document. Hosting providers may process
            technical request information such as IP addresses; provider,
            retention and processing arrangements must be confirmed before
            publication.
          </p>
          <h2>Cookies and storage</h2>
          <p>
            The application does not intentionally set analytics cookies or
            persist form entries in browser storage. Infrastructure and hosting
            cookies require assessment before launch.
          </p>
          <h2>Before collecting real information</h2>
          <p>
            The operator’s legal identity, postal and privacy contact details,
            purposes and lawful bases, processors, transfers, retention,
            security and rights handling must be documented. The reviewed notice
            must explain applicable GDPR rights and how to raise concerns with
            Ireland’s Data Protection Commission.
          </p>
          <h2>No customer information</h2>
          <p>
            Do not enter customer or sensitive information. Live WhatsApp,
            identity and invoice processing require a separate assessment and
            updated notice.
          </p>
        </>
      )}
      <p>
        Draft dated 15 October 2026. Operator and contact details await
        verification. <Link href="/contact">Contact preview</Link>.
      </p>
    </main>
  );
}
