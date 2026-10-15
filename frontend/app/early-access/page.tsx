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
          We’re building Tara around the people who’ll use it. Tell us a little
          about your trade and the paperwork you’d most like a hand with.
        </p>
        <p>
          Early access is not open yet. Prepare a local interest draft here;
          online registration will follow once our signup service and privacy
          information are ready.
        </p>
        <span className="pill">NO PAYMENT DETAILS · NO COMMITMENT</span>
      </div>
      <EnquiryForm />
    </main>
  );
}
