import type { Metadata } from "next";
import "./globals.css";
import { Header, Footer } from "@/components/shell";
export const metadata: Metadata = {
  title: {
    default: "An Oifig — Your office, in your pocket.",
    template: "%s | An Oifig",
  },
  description:
    "Meet Tara, the WhatsApp administrative assistant being built for Irish tradespeople. Explore invoice drafting and approval in our interactive demonstration.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "An Oifig — Your office, in your pocket.",
    description: "Less time at the kitchen table. More time for yourself.",
    locale: "en_IE",
    type: "website",
  },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IE">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <Header />
        {children}
        <Footer />
      </body>
    </html>
  );
}
