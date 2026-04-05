"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

const SECTION_LINKS = [
  { label: "About", href: "/#about" },
  { label: "Features", href: "/#features" },
  { label: "Developers", href: "/#developers" },
  { label: "Chat", href: "/chat" },
  { label: "Contributors", href: "/contributors" },
] as const;

function NavLinks({
  onNavigate,
  pathname,
  centerOnMobile = false,
}: {
  onNavigate?: () => void;
  pathname: string | null;
  /** Stack + center link text (hamburger menu on small screens only). */
  centerOnMobile?: boolean;
}) {
  return (
    <>
      {SECTION_LINKS.map(({ label, href }) => {
        const isActive = pathname === href;
        return (
          <li
            key={label}
            className={centerOnMobile ? "w-full text-center" : undefined}
          >
            <Link
              href={href}
              onClick={onNavigate}
              className={`text-[1.05rem] no-underline transition-colors duration-200 ${
                isActive
                  ? "text-accent"
                  : "text-white hover:text-accent"
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
      className={`inline-flex cursor-pointer items-center justify-center rounded-md border border-white/25 bg-transparent px-[18px] py-[7px] text-[1.05rem] text-white no-underline transition-all duration-200 hover:border-accent hover:bg-accent/10 hover:text-accent ${className ?? ""}`}
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
          className="flex shrink-0 items-center gap-2.5 font-mono text-[1.25rem] font-bold no-underline"
        >
          <Image
            src="/chatvector-logo.svg"
            alt=""
            width={40}
            height={40}
            unoptimized
            className="size-10 shrink-0"
          />
          <span className="text-[1.5rem] bg-gradient-to-r from-accent to-blue bg-clip-text text-transparent">
            ChatVector
          </span>
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
            className="cursor-pointer rounded-md border border-border bg-transparent px-3 py-2 text-lg leading-none text-white hover:text-blue md:hidden"
          >
            {mobileOpen ? "✕" : "☰"}
          </button>
        </div>
      </nav>

      {mobileOpen ? (
        <div className="flex flex-col items-center gap-4 border-t border-border p-4 md:hidden">
          <ul className="m-0 flex w-full list-none flex-col items-center gap-4 p-0">
            <NavLinks
              pathname={pathname}
              centerOnMobile
              onNavigate={() => setMobileOpen(false)}
            />
          </ul>
          <div className="flex justify-center">
            <GitHubButton />
          </div>
        </div>
      ) : null}
    </header>
  );
}
