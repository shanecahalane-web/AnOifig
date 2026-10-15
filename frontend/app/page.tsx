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
  Sparkles,
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
              You know your trade.
              <br />
              Let Tara help with the paperwork.
            </p>
            <p className="hero-detail">
              Meet the WhatsApp assistant we’re building for the business behind
              your work. Start with an invoice. Get back to your evening.
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
              <MessageCircle size={16} /> Built around WhatsApp. No new habits
              needed.
            </div>
          </div>
          <div className="hero-visual">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <span className="visual-label">YOUR NEW OFFICE ASSISTANT</span>
            <div className="hero-card">
              <div className="hero-card-top">
                <span className="avatar">T</span>
                <div>
                  <strong>Tara</strong>
                  <span>Paperwork, meet your match.</span>
                </div>
                <Sparkles size={18} />
              </div>
              <div className="mini-bubble">
                Finished the job.
                <br />
                Can you help with the invoice?
              </div>
              <div className="mini-reply">
                Absolutely. Let’s get a draft
                <br />
                ready for you to check.
              </div>
              <div className="mini-document">
                <FileText size={30} />
                <div>
                  <strong>One less thing on your list.</strong>
                  <span>Draft. Check. Approve.</span>
                </div>
                <Check size={18} />
              </div>
              <div className="card-foot">
                <span className="status-dot" /> A LOOK AT WHAT’S COMING
              </div>
            </div>
            <div className="visual-caption">
              <span>Less paperwork.</span>
              <em>More headspace.</em>
            </div>
          </div>
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
      <section className="section demo-section" id="demo">
        <div className="section-copy">
          <div className="eyebrow">01 / MEET TARA</div>
          <h2>
            A conversation.
            <br />
            <em>Not another chore.</em>
          </h2>
          <p>
            No forms to wrestle with after a long day. Tell Tara what you need
            in plain English, fill in the gaps, and check the draft before you
            approve it.
          </p>
          <p>
            This is a little taste of the experience we’re building. Try the
            invoice conversation for yourself.
          </p>
          <div className="demo-instruction">
            <span>↗</span>
            <div>
              <strong>Take Tara for a test run</strong>
              <p>
                Tap the button beneath the phone to move the conversation along.
              </p>
            </div>
          </div>
          <div className="outline-note">
            Interactive concept · Fictional customer and invoice · No live
            services
          </div>
        </div>
        <Demo />
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
              text: "Share who the invoice is for, what you did, and the agreed amount. Tara asks for anything missing.",
            },
            {
              n: "02",
              icon: FileText,
              title: "Check the draft",
              text: "Review the customer, work, amount and payment details. Make changes before moving ahead.",
            },
            {
              n: "03",
              icon: ShieldCheck,
              title: "Give your approval",
              text: "You explicitly approve the draft. This preview records a simulated approval; it never issues an invoice.",
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
            Invoicing is the first workflow we’re exploring. A straightforward
            way to turn job details into a draft, with your review at the
            centre.
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
              <Check />A clear draft to review and approve
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
            Good help.
            <br />
            <em>Clear pricing.</em>
          </h2>
          <p>
            We’re still working out the right plan for independent tradespeople
            and small teams. Join early access to hear when it’s ready.
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
              Hear about availability and pricing
            </li>
            <li>
              <Check size={17} />
              No purchase or subscription today
            </li>
          </ul>
          <Link href="/early-access" className="button">
            Put your name down <ArrowUpRight size={17} />
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
              "The demo uses fictional, illustrative amounts. It is not a tax calculation or accounting service. Tax treatment and document requirements need review before any real invoice is issued.",
            ],
            [
              "How much will it cost?",
              "Pricing is still being developed. There are no confirmed plans, charges or subscriptions on this website.",
            ],
            [
              "What happens to information I enter here?",
              "This preview does not submit or store form entries. You can download your enquiry locally. A privacy notice and secure signup service need to be finalised before real data collection begins.",
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
