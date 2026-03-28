"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

const SECTION_LINKS = [
  { label: "About", href: "/#about" },
  { label: "Features", href: "/#features" },
  { label: "Developers", href: "/#developers" },
] as const;

function NavLinks({
  onNavigate,
  pathname,
}: {
  onNavigate?: () => void;
  pathname: string | null;
}) {
  const demoActive = pathname === "/chat";

  return (
    <>
      {SECTION_LINKS.map(({ label, href }) => (
        <li key={label}>
          <Link
            href={href}
            onClick={onNavigate}
            style={{
              color: "#6b7685",
              textDecoration: "none",
              fontSize: "0.9rem",
              transition: "color .2s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "#e8edf5";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "#6b7685";
            }}
          >
            {label}
          </Link>
        </li>
      ))}
      <li>
        <Link
          href="/chat"
          onClick={onNavigate}
          style={{
            color: demoActive ? "#00e5a0" : "#6b7685",
            textDecoration: "none",
            fontSize: "0.9rem",
            transition: "color .2s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#e8edf5";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = demoActive ? "#00e5a0" : "#6b7685";
          }}
        >
          Demo
        </Link>
      </li>
    </>
  );
}

function GitHubButton({ className }: { className?: string }) {
  return (
    <a
      href={GITHUB_REPO}
      target="_blank"
      rel="noopener noreferrer"
      className={className}
      style={{
        background: "transparent",
        border: "1px solid #00e5a0",
        color: "#00e5a0",
        padding: "7px 18px",
        borderRadius: 6,
        fontSize: "0.85rem",
        cursor: "pointer",
        textDecoration: "none",
        transition: "all .2s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "#00e5a0";
        e.currentTarget.style.color = "#000";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
        e.currentTarget.style.color = "#00e5a0";
      }}
    >
      GitHub
    </a>
  );
}

export default function Navigation() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        background: "rgba(10,12,16,0.88)",
        backdropFilter: "blur(14px)",
        borderBottom: "1px solid #1e2530",
      }}
    >
      <nav
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          padding: "0 1rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
          minHeight: 60,
        }}
      >
        <Link
          href="/"
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "1.05rem",
            fontWeight: 700,
            color: "#00e5a0",
            textDecoration: "none",
            flexShrink: 0,
          }}
        >
          Chat
          <span style={{ color: "#e8edf5", opacity: 0.45 }}>&lt;</span>
          Vector
          <span style={{ color: "#e8edf5", opacity: 0.45 }}>&gt;</span>
        </Link>

        <ul className="hidden md:flex list-none flex-1 flex-row flex-wrap items-center justify-center gap-8 m-0 p-0">
          <NavLinks pathname={pathname} />
        </ul>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            flexShrink: 0,
          }}
        >
          <GitHubButton className="hidden md:inline-flex" />
          <button
            type="button"
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            onClick={() => setMobileOpen((o) => !o)}
            className="md:hidden"
            style={{
              background: "transparent",
              border: "1px solid #1e2530",
              color: "#e8edf5",
              borderRadius: 6,
              padding: "8px 12px",
              fontSize: "1rem",
              lineHeight: 1,
              cursor: "pointer",
            }}
          >
            {mobileOpen ? "✕" : "☰"}
          </button>
        </div>
      </nav>

      {mobileOpen ? (
        <div
          className="md:hidden"
          style={{
            borderTop: "1px solid #1e2530",
            padding: "1rem",
            display: "flex",
            flexDirection: "column",
            gap: "1rem",
          }}
        >
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: "1rem",
            }}
          >
            <NavLinks
              pathname={pathname}
              onNavigate={() => setMobileOpen(false)}
            />
          </ul>
          <div style={{ alignSelf: "flex-start" }}>
            <GitHubButton />
          </div>
        </div>
      ) : null}
    </header>
  );
}
