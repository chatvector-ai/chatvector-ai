"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

const SECTION_LINKS = [
  { label: "About", href: "/#about" },
  { label: "Features", href: "/#features" },
  { label: "Developers", href: "/#developers" },
  { label: "Chat", href: "/chat" },
] as const;

function NavLinks({
  onNavigate,
  pathname,
}: {
  onNavigate?: () => void;
  pathname: string | null;
}) {
  return (
    <>
      {SECTION_LINKS.map(({ label, href }) => {
        const chatActive = href === "/chat" && pathname === "/chat";
        return (
          <li key={label}>
            <Link
              href={href}
              onClick={onNavigate}
              className={`text-[0.9rem] no-underline transition-colors duration-200 ${
                chatActive
                  ? "text-accent"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </>
  );
}

function GitHubButton({ className }: { className?: string }) {
  return (
    <a
      href={GITHUB_REPO}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex cursor-pointer items-center justify-center rounded-md border border-accent bg-transparent px-[18px] py-[7px] text-[0.85rem] text-accent no-underline transition-all duration-200 hover:bg-accent hover:text-black ${className ?? ""}`}
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
      className="sticky top-0 z-[100] border-b border-border backdrop-blur-[14px]"
      style={{ background: "rgba(10,12,16,0.88)" }}
    >
      {/* Header scrim: 88% of page background rgba — inline for exact match with backdrop-blur */}
      <nav className="mx-auto flex min-h-[60px] max-w-[1100px] items-center justify-between gap-4 px-4">
        <Link
          href="/"
          className="shrink-0 font-mono text-[1.05rem] font-bold text-accent no-underline"
        >
          Chat
          <span className="text-foreground/45">&lt;</span>
          Vector
          <span className="text-foreground/45">&gt;</span>
        </Link>

        <ul className="m-0 hidden list-none flex-1 flex-row flex-wrap items-center justify-center gap-8 p-0 md:flex">
          <NavLinks pathname={pathname} />
        </ul>

        <div className="flex shrink-0 items-center gap-3">
          <GitHubButton className="hidden md:inline-flex" />
          <button
            type="button"
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            onClick={() => setMobileOpen((o) => !o)}
            className="cursor-pointer rounded-md border border-border bg-transparent px-3 py-2 text-base leading-none text-foreground md:hidden"
          >
            {mobileOpen ? "✕" : "☰"}
          </button>
        </div>
      </nav>

      {mobileOpen ? (
        <div className="flex flex-col gap-4 border-t border-border p-4 md:hidden">
          <ul className="m-0 flex list-none flex-col gap-4 p-0">
            <NavLinks
              pathname={pathname}
              onNavigate={() => setMobileOpen(false)}
            />
          </ul>
          <div className="self-start">
            <GitHubButton />
          </div>
        </div>
      ) : null}
    </header>
  );
}
