import Link from "next/link";
export default function Page() {
  return (
    <main id="main" className="section inner-page">
      <div className="eyebrow">404 / A LITTLE OFF THE TOOLS</div>
      <h1>
        Let’s get you
        <br />
        <em>back on track.</em>
      </h1>
      <p>That page isn’t here.</p>
      <Link href="/" className="button">
        Back to An Oifig
      </Link>
    </main>
  );
}
