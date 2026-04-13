"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import ThemeToggle from "./ThemeToggle";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

const MAIN_NAV_LINKS = [
  { label: "About", href: "/about" },
  { label: "Chat", href: "/chat" },
  { label: "Contributors", href: "/contributors" },
] as const;

const DOC_LINKS = [
  { label: "Getting Started", href: "/getting-started" },
  { label: "Architecture", href: "/architecture" },
  { label: "SDK", href: "/sdk" },
  { label: "Roadmap", href: "/roadmap" },
  { label: "Contributing", href: "/contributing" },
] as const;

function isDocsActive(pathname: string | null): boolean {
  if (!pathname) return false;
  return DOC_LINKS.some((l) => pathname.startsWith(l.href));
}

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
      {MAIN_NAV_LINKS.map(({ label, href }) => {
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
  const [docsOpen, setDocsOpen] = useState(false);

  const docsActive = isDocsActive(pathname);

  return (
    <header
      className="sticky top-0 z-[100] border-b border-border backdrop-blur-[14px]"
      style={{ background: "rgba(10,12,16,0.88)" }}
    >
      {/* Header scrim: 88% of page background rgba — inline for exact match with backdrop-blur */}
      <nav className="mx-auto flex min-h-[60px] max-w-[1100px] items-center justify-between gap-4 px-4">
        <Link
          href="/"
          className="flex shrink-0 items-center font-mono text-[1.25rem] font-bold no-underline"
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
          <li className="group relative">
            <button
              type="button"
              aria-haspopup="menu"
              className={`flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[1.05rem] no-underline transition-colors duration-200 ${
                docsActive
                  ? "text-accent"
                  : "text-white hover:text-accent"
              }`}
            >
              Docs
              <ChevronDown
                aria-hidden
                className="size-[1em] shrink-0 transition-transform duration-200 group-hover:rotate-180 group-focus-within:rotate-180"
              />
            </button>
            <div className="pointer-events-none invisible absolute right-0 top-full z-50 pt-2 opacity-0 transition-[opacity,visibility] duration-200 group-hover:pointer-events-auto group-hover:visible group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:opacity-100">
              <div
                className="min-w-[180px] rounded-xl border border-border bg-surface py-2"
                role="menu"
              >
                {DOC_LINKS.map(({ label, href }) => (
                  <Link
                    key={href}
                    href={href}
                    role="menuitem"
                    className="block px-4 py-2 text-[0.9rem] text-muted no-underline transition-colors hover:text-foreground"
                  >
                    {label}
                  </Link>
                ))}
              </div>
            </div>
          </li>
        </ul>

        <div className="flex shrink-0 items-center gap-3">
          <GitHubButton className="hidden md:inline-flex" />
          <ThemeToggle />
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
            <li className="w-full text-center">
              <button
                type="button"
                aria-expanded={docsOpen}
                onClick={() => setDocsOpen((o) => !o)}
                className={`inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[1.05rem] no-underline transition-colors duration-200 ${
                  docsActive
                    ? "text-accent"
                    : "text-white hover:text-accent"
                }`}
              >
                Docs
                <ChevronDown
                  aria-hidden
                  className={`size-[1em] shrink-0 transition-transform duration-200 ${
                    docsOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
              {docsOpen ? (
                <ul className="m-0 mt-3 flex list-none flex-col items-stretch gap-2 p-0 pl-4">
                  {DOC_LINKS.map(({ label, href }) => (
                    <li key={href} className="w-full text-center">
                      <Link
                        href={href}
                        onClick={() => {
                          setMobileOpen(false);
                          setDocsOpen(false);
                        }}
                        className="block px-4 py-2 text-[0.9rem] text-muted no-underline transition-colors hover:text-foreground"
                      >
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          </ul>
          <div className="flex justify-center">
            <GitHubButton />
          </div>
        </div>
      ) : null}
    </header>
  );
}
