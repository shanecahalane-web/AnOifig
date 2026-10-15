import EnquiryForm from "@/components/enquiry-form";
export const metadata = { title: "Early access" };
export default function Page() {
  return (
    <main id="main" className="section inner-page form-page">
      <div>
        <div className="eyebrow">BE PART OF WHAT’S NEXT</div>
        <h1>
          Less admin.
          <br />
          <em>More possibility.</em>
        </h1>
        <p>
          We’re building Tara around the people who’ll use it. Explore a
          straightforward signup experience designed for your trade.
        </p>
        <p>
          Real signup is not open yet. Try the form with sample details; nothing
          will be sent or saved. We’ll connect registration only after the
          secure service and privacy policies are ready.
        </p>
        <span className="pill">NO PAYMENT DETAILS · NO COMMITMENT</span>
      </div>
      <EnquiryForm />
    </main>
  );
}
