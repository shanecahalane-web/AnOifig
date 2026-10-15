import Link from "next/link";
import {
  ArrowDown,
  ArrowUpRight,
  Check,
  FileText,
  MessageCircle,
  Mic,
  Clock3,
  ClipboardList,
  ShieldCheck,
  Wallet,
  BriefcaseBusiness,
  Users,
} from "lucide-react";
import Demo from "@/components/demo";
import { pricing } from "@/lib/site-config";
export default function Home() {
  return (
    <main id="main">
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="status-dot" /> MADE FOR IRISH TRADESPEOPLE
            </div>
            <h1>
              Your office,
              <br />
              in your <em>pocket.</em>
            </h1>
            <p className="hero-description">
              Meet Tara, your WhatsApp assistant for invoices and everyday
              business admin.
            </p>
            <p className="hero-detail">
              Less time on paperwork. More time getting the job done. Built for
              independent tradespeople and small teams in Ireland.
            </p>
            <div className="hero-actions">
              <Link className="button gold" href="/early-access">
                Get early access <ArrowUpRight size={18} />
              </Link>
              <a className="text-link" href="#demo">
                Meet Tara <ArrowDown size={16} />
              </a>
            </div>
            <div className="hero-note">
              <MessageCircle size={16} /> In development. Try the simulated
              experience.
            </div>
          </div>
          <Demo />
        </div>
        <div className="hero-bottom">
          <span>FOR THE BUSINESS AFTER THE JOB</span>
          <a href="#demo">
            A better way to finish your day <ArrowDown size={14} />
          </a>
          <span>AN OIFIG / YOUR OFFICE</span>
        </div>
      </section>
      <div className="principles">
        <span>
          <MessageCircle />
          As simple as a message
        </span>
        <span>
          <ShieldCheck />
          You stay in control
        </span>
        <span>
          <Clock3 />
          Designed around your day
        </span>
      </div>
      <section className="section demo-section" id="review-and-approve">
        <div className="section-copy">
          <div className="eyebrow">01 / MEET TARA</div>
          <h2>
            A change of plan.
            <br />
            <em>A simple message.</em>
          </h2>
          <p>
            The amount changed? Just tell Tara. See the new draft, check the
            details, and approve the version you’re happy with. You stay in
            control from the first message to the final check.
          </p>
          <p>
            In our demonstration, €450 becomes €500 before illustrative VAT. The
            document updates, and the revised version needs your review again.
          </p>
          <div className="demo-instruction">
            <span>↗</span>
            <div>
              <strong>Try a correction for yourself</strong>
              <p>
                Open the invoice in the demo, change the amount and review the
                updated draft.
              </p>
            </div>
          </div>
          <div className="outline-note">
            Interactive concept · Fictional customer and invoice · No live
            services
          </div>
        </div>
        <div
          className="revision-story"
          aria-label="Illustration of an invoice correction"
        >
          <div className="revision-heading">
            <FileText size={20} />
            <span>ONE JOB. ONE CLEAR RECORD.</span>
            <span className="pill">SAMPLE</span>
          </div>
          <div className="revision-message">
            “Actually, change the amount to €500.”
            <span>Just a message. That’s all.</span>
          </div>
          <div className="revision-document">
            <div>
              <span>JOHN MURPHY · SHOWER REPLACEMENT</span>
              <strong>
                Invoice draft <span>v2</span>
              </strong>
            </div>
            <dl>
              <div>
                <dt>Previous subtotal</dt>
                <dd>
                  <s>€450.00</s>
                </dd>
              </div>
              <div>
                <dt>Updated subtotal</dt>
                <dd>€500.00</dd>
              </div>
              <div>
                <dt>Illustrative VAT · 13.5%</dt>
                <dd>€67.50</dd>
              </div>
              <div className="revision-total">
                <dt>Sample total</dt>
                <dd>€567.50</dd>
              </div>
            </dl>
            <div className="revision-check">
              <ShieldCheck size={17} />
              Awaiting your review and approval
            </div>
          </div>
          <a href="#demo" className="text-link">
            Try the interactive version <ArrowUpRight size={16} />
          </a>
        </div>
      </section>
      <section className="section how-section" id="how-it-works">
        <div className="section-heading">
          <div>
            <div className="eyebrow">02 / HOW IT WORKS</div>
            <h2>
              From job done
              <br />
              to <em>admin sorted.</em>
            </h2>
          </div>
          <p>
            A few messages. A clear draft.
            <br />
            The final say is always yours.
          </p>
        </div>
        <div className="steps">
          {[
            {
              n: "01",
              icon: MessageCircle,
              title: "Tell Tara about the job",
              text: "Share the customer, the work and the agreed amount in an ordinary message. No complicated software to learn.",
            },
            {
              n: "02",
              icon: FileText,
              title: "Check the draft",
              text: "Open the invoice, check the details and ask for a correction. Tara prepares a new version for you to review.",
            },
            {
              n: "03",
              icon: ShieldCheck,
              title: "Give your approval",
              text: "Approve the version you’ve reviewed, then download a clearly marked sample PDF. This demo never issues or sends an invoice.",
            },
          ].map((s) => (
            <article className="step" key={s.n}>
              <div className="step-top">
                <s.icon size={26} />
                <span>{s.n}</span>
              </div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="section features-section" id="features">
        <div className="feature-main">
          <div className="eyebrow">03 / A SMALLER ADMIN PILE</div>
          <h2>
            Start with invoices.
            <br />
            <em>Build from there.</em>
          </h2>
          <p>
            An AI-powered WhatsApp admin assistant, starting with the paperwork
            at the end of a job. Try invoice creation, corrections and approval
            here — all simulated, all under your control.
          </p>
          <ul className="feature-list">
            <li>
              <Check />
              Natural, message-based requests
            </li>
            <li>
              <Check />A helping hand with missing details
            </li>
            <li>
              <Check />
              Review and approve the current draft
            </li>
            <li>
              <Check />
              Download a clearly marked sample PDF
            </li>
          </ul>
          <span className="pill">INVOICING · INTERACTIVE DEMONSTRATION</span>
        </div>
        <div className="coming">
          <div className="coming-header">
            <span>ON THE WORKBENCH</span>
            <span className="pill">PLANNED</span>
          </div>
          <h3>More help. In good time.</h3>
          <p>
            These ideas are on our roadmap, not available features. Early
            feedback will help shape what comes next.
          </p>
          {[
            {
              icon: ClipboardList,
              title: "Quotations",
              text: "A clearer start to the next job.",
            },
            {
              icon: Mic,
              title: "Voice notes",
              text: "Say it while it’s fresh in your mind.",
            },
            {
              icon: Clock3,
              title: "Payment reminders",
              text: "A little help with the follow-up.",
            },
            {
              icon: Wallet,
              title: "Expense tracking",
              text: "Keep the little costs in view.",
            },
            {
              icon: BriefcaseBusiness,
              title: "Job management",
              text: "The details behind every job.",
            },
            {
              icon: Users,
              title: "Customer follow-ups",
              text: "Keep the next conversation moving.",
            },
          ].map((f) => (
            <div className="planned" key={f.title}>
              <f.icon size={21} />
              <div>
                <strong>{f.title}</strong>
                <span>{f.text}</span>
              </div>
              <span className="planned-tag">Coming soon</span>
            </div>
          ))}
        </div>
      </section>
      <section className="section pricing-section" id="pricing">
        <div>
          <div className="eyebrow">04 / KEEPING IT STRAIGHTFORWARD</div>
          <h2>
            Built around
            <br />
            <em>your working day.</em>
          </h2>
          <p>
            We’re shaping Tara for independent tradespeople and small teams.
            Explore the early-access experience and see what joining will look
            like before signup opens.
          </p>
        </div>
        <div className="price-card">
          <div className="price-top">
            <span>EARLY ACCESS</span>
            <span className="pill">IN DEVELOPMENT</span>
          </div>
          <h3>{pricing.heading}</h3>
          <p>{pricing.description}</p>
          <ul>
            <li>
              <Check size={17} />
              Help shape Tara’s first workflows
            </li>
            <li>
              <Check size={17} />
              Preview a simple signup experience
            </li>
            <li>
              <Check size={17} />
              No purchase or subscription today
            </li>
          </ul>
          <Link href="/early-access" className="button">
            Explore early access <ArrowUpRight size={17} />
          </Link>
          <small>{pricing.disclaimer}</small>
        </div>
      </section>
      <section className="section faq-section">
        <div>
          <div className="eyebrow">05 / A FEW GOOD QUESTIONS</div>
          <h2>
            Before you
            <br />
            <em>head off.</em>
          </h2>
        </div>
        <div className="faqs">
          {[
            [
              "Is Tara available to use today?",
              "Not yet. This website demonstrates the experience we’re building. The conversation is a front-end simulation, and early access timing has not been confirmed.",
            ],
            [
              "Do I need to install another app?",
              "The intended experience is built around WhatsApp. This website is a preview; a live WhatsApp service is not connected.",
            ],
            [
              "Will Tara send an invoice without asking me?",
              "The demonstrated workflow asks you to review and explicitly approve a draft. No invoice is issued or sent by this website.",
            ],
            [
              "What about VAT and accounting advice?",
              "The invoice uses a fixed 13.5% illustrative VAT rate and fictional details so you can see how totals change. The rate is an assumption, not advice for your work. Sample PDFs are clearly marked and are not tax invoices.",
            ],
            [
              "How much will it cost?",
              "Pricing is still being developed. There are no confirmed plans, charges or subscriptions on this website.",
            ],
            [
              "What happens to information I enter here?",
              "Signup and contact forms are clearly labelled demonstrations. Use sample details: nothing is transmitted or stored, and no waiting-list entry is created. A secure service and reviewed privacy information are required before real signup opens.",
            ],
          ].map(([q, a]) => (
            <details key={q}>
              <summary>
                {q}
                <span>+</span>
              </summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>
      <section className="closing">
        <div className="eyebrow">LEAVE THE PAPERWORK AT WORK.</div>
        <h2>
          Your evening
          <br />
          looks better <em>without it.</em>
        </h2>
        <Link className="button gold" href="/early-access">
          Meet your future office assistant <ArrowUpRight size={18} />
        </Link>
        <p>For the work you do. And the life after it.</p>
      </section>
    </main>
  );
}
