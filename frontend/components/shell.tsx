"use client";
import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import { ArrowUpRight, Menu, X } from "lucide-react";
// Official logo integration points: Header and Footer .brand links.
// Keep the existing text branding until the approved asset is supplied.
export function Header() {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  return (
    <header className="header">
      <div className="nav-wrap">
        <Link href="/" className="brand" aria-label="An Oifig home">
          An Oifig<span className="brand-period">.</span>
        </Link>
        <button
          ref={menuButton}
          className="menu-button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="navigation"
          onClick={() => setOpen(!open)}
        >
          {open ? <X /> : <Menu />}
        </button>
        <nav
          id="navigation"
          className={open ? "nav open" : "nav"}
          aria-label="Main navigation"
          onClick={() => setOpen(false)}
        >
          <Link href="/#how-it-works">How it works</Link>
          <Link href="/#features">What Tara does</Link>
          <Link href="/#pricing">Pricing</Link>
          <Link href="/contact">Contact</Link>
          <Link className="button small" href="/early-access">
            Join early access <ArrowUpRight size={16} />
          </Link>
        </nav>
      </div>
    </header>
  );
}
export function Footer() {
  return (
    <footer>
      <div className="footer-top">
        <div>
          <Link href="/" className="brand">
            An Oifig<span className="brand-period">.</span>
          </Link>
          <p>
            A little less admin.
            <br />A little more life.
          </p>
        </div>
        <div className="footer-links">
          <Link href="/early-access">Early access</Link>
          <Link href="/contact">Get in touch</Link>
          <Link href="/privacy">Privacy draft</Link>
          <Link href="/terms">Terms draft</Link>
        </div>
      </div>
      <div className="footer-bottom">
        <span>
          © {new Date().getFullYear()} An Oifig. Made for the way you work.
        </span>
        <span>Built with Irish tradespeople in mind.</span>
      </div>
    </footer>
  );
}
