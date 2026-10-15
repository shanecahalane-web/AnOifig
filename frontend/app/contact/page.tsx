import EnquiryForm from "@/components/enquiry-form";
export const metadata = { title: "Contact" };
export default function Page() {
  return (
    <main id="main" className="section inner-page form-page">
      <div>
        <div className="eyebrow">LET’S TALK SHOP</div>
        <h1>
          Good ideas
          <br />
          start with <em>a chat.</em>
        </h1>
        <p>
          A question about Tara? An idea from your working day? We’d like to
          make room for both.
        </p>
        <p>
          This preview has no connected inbox or verified contact address.
          Prepare and save your enquiry locally. A direct contact channel will
          be added before launch.
        </p>
      </div>
      <EnquiryForm contact />
    </main>
  );
}
