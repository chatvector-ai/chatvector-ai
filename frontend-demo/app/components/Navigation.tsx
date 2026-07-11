"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, Github } from "lucide-react";
import { useState } from "react";
import ThemeToggle from "./ThemeToggle";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

const ABOUT_LINK = { label: "About", href: "/about" } as const;

const DEMO_LINKS = [
  { label: "Chat", href: "/chat" },
  { label: "Batch", href: "/batch" },
  { label: "Status", href: "/status" },
] as const;

const CONTRIBUTORS_LINK = {
  label: "Contributors",
  href: "/contributors",
} as const;

const DOC_LINKS = [
  { label: "Getting Started", href: "/getting-started" },
  { label: "Architecture", href: "/architecture" },
  { label: "SDK", href: "/sdk" },
  { label: "Roadmap", href: "/roadmap" },
  { label: "Contributing", href: "/contributing" },
] as const;

function isNavGroupActive(
  pathname: string | null,
  links: ReadonlyArray<{ href: string }>,
): boolean {
  if (!pathname) return false;
  return links.some((link) => pathname.startsWith(link.href));
}

function NavLinks({
  links,
  onNavigate,
  pathname,
  centerOnMobile = false,
}: {
  links: ReadonlyArray<{ label: string; href: string }>;
  onNavigate?: () => void;
  pathname: string | null;
  /** Stack + center link text (hamburger menu on small screens only). */
  centerOnMobile?: boolean;
}) {
  return (
    <>
      {links.map(({ label, href }) => {
        const isActive = pathname === href;
        return (
          <li
            key={label}
            className={centerOnMobile ? "w-full text-center" : undefined}
          >
            <Link
              href={href}
              onClick={onNavigate}
              className={`text-base text-bold no-underline text-[1.15rem] transition-colors duration-200 ${
                isActive ? "text-accent" : "text-foreground hover:text-accent"
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

function GitHubNavLink() {
  return (
    <a
      href={GITHUB_REPO}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="View ChatVector on GitHub"
      className="inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-transparent p-2 text-base leading-none text-foreground no-underline transition-all duration-200 hover:border-accent hover:bg-accent/10 hover:text-accent md:px-[18px] md:py-2"
    >
      <Github
        className="size-[1.1rem] shrink-0 md:hidden"
        strokeWidth={1.75}
        aria-hidden
      />
      <span className="hidden md:inline">GitHub</span>
    </a>
  );
}

export default function Navigation() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  /** Desktop flyout: sync aria-expanded with hover / focus-within */
  const [demoFlyoutOpen, setDemoFlyoutOpen] = useState(false);
  const [docsFlyoutOpen, setDocsFlyoutOpen] = useState(false);

  const demoActive = isNavGroupActive(pathname, DEMO_LINKS);
  const docsActive = isNavGroupActive(pathname, DOC_LINKS);

  return (
    <header
      className="sticky top-0 z-[100] border-b border-border backdrop-blur-[14px]"
      style={{ background: "var(--nav-bg)" }}
    >
      {/* Header scrim: 88% of active theme background — see --nav-bg token in globals.css */}
      <nav className="mx-auto flex min-h-[60px] max-w-[1100px] items-center justify-between gap-4 px-3 py-2">
        <Link
          href="/"
          className="flex shrink-0 items-center gap-1.5 font-mono font-bold no-underline md:gap-2"
        >
          {/* Both images rendered; CSS shows/hides based on data-theme on <html> */}
          <Image
            src="/chatvector-logo-dark.svg"
            alt=""
            width={70}
            height={70}
            unoptimized
            className="size-9 shrink-0 md:size-10 lg:size-12 [[data-theme=light]_&]:hidden"
          />
          <Image
            src="/chatvector-logo-light.svg"
            alt=""
            width={70}
            height={70}
            unoptimized
            className="size-9 shrink-0 hidden md:size-10 lg:size-12 [[data-theme=light]_&]:block"
          />
          <span className="whitespace-nowrap text-[1.2rem] leading-tight text-transparent md:text-[1.45rem] lg:text-[1.7rem] bg-gradient-to-r from-accent to-blue bg-clip-text">
            ChatVector
          </span>
        </Link>

        <ul className="m-0 hidden list-none flex-1 flex-row flex-wrap items-center justify-center gap-6 p-0 md:flex lg:gap-8">
          <NavLinks links={[ABOUT_LINK]} pathname={pathname} />
          <li
            className="group relative"
            onMouseEnter={() => setDemoFlyoutOpen(true)}
            onMouseLeave={() => setDemoFlyoutOpen(false)}
            onFocusCapture={() => setDemoFlyoutOpen(true)}
            onBlurCapture={(e) => {
              const next = e.relatedTarget;
              if (next instanceof Node && e.currentTarget.contains(next))
                return;
              setDemoFlyoutOpen(false);
            }}
          >
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={demoFlyoutOpen}
              aria-controls="demo-menu"
              className={`flex cursor-pointer text-[1.15rem] items-center gap-1 border-0 bg-transparent p-0 text-base no-underline transition-colors duration-200 ${
                demoActive ? "text-accent" : "text-foreground hover:text-accent"
              }`}
            >
              Demo
              <ChevronDown
                aria-hidden
                className="size-[1em] shrink-0 transition-transform duration-200 group-hover:rotate-180 group-focus-within:rotate-180"
              />
            </button>
            <div className="pointer-events-none invisible absolute left-0 top-full z-50 pt-2 opacity-0 transition-[opacity,visibility] duration-200 group-hover:pointer-events-auto group-hover:visible group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:opacity-100">
              <div
                id="demo-menu"
                className="min-w-[180px] rounded-xl border border-border bg-surface py-2"
                role="menu"
              >
                {DEMO_LINKS.map(({ label, href }) => (
                  <Link
                    key={href}
                    href={href}
                    role="menuitem"
                    className="block px-4 py-2 text-base text-muted no-underline transition-colors hover:text-foreground"
                  >
                    {label}
                  </Link>
                ))}
              </div>
            </div>
          </li>
          <NavLinks links={[CONTRIBUTORS_LINK]} pathname={pathname} />
          <li
            className="group relative"
            onMouseEnter={() => setDocsFlyoutOpen(true)}
            onMouseLeave={() => setDocsFlyoutOpen(false)}
            onFocusCapture={() => setDocsFlyoutOpen(true)}
            onBlurCapture={(e) => {
              const next = e.relatedTarget;
              if (next instanceof Node && e.currentTarget.contains(next))
                return;
              setDocsFlyoutOpen(false);
            }}
          >
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={docsFlyoutOpen}
              aria-controls="docs-menu"
              className={`flex cursor-pointer text-[1.15rem] items-center gap-1 border-0 bg-transparent p-0 text-base no-underline transition-colors duration-200 ${
                docsActive ? "text-accent" : "text-foreground hover:text-accent"
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
                id="docs-menu"
                className="min-w-[180px] rounded-xl border border-border bg-surface py-2"
                role="menu"
              >
                {DOC_LINKS.map(({ label, href }) => (
                  <Link
                    key={href}
                    href={href}
                    role="menuitem"
                    className="block px-4 py-2 text-base text-muted no-underline transition-colors hover:text-foreground"
                  >
                    {label}
                  </Link>
                ))}
              </div>
            </div>
          </li>
        </ul>

        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <GitHubNavLink />
          <ThemeToggle />
          <button
            type="button"
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            onClick={() => setMobileOpen((o) => !o)}
            className="cursor-pointer rounded-md border border-border bg-transparent px-3 py-2 text-lg leading-none text-foreground hover:text-blue md:hidden"
          >
            {mobileOpen ? "✕" : "☰"}
          </button>
        </div>
      </nav>

      {mobileOpen ? (
        <div className="flex flex-col items-center gap-4 border-t border-border p-4 md:hidden">
          <ul className="m-0 flex w-full list-none flex-col items-center gap-4 p-0">
            <NavLinks
              links={[ABOUT_LINK]}
              pathname={pathname}
              centerOnMobile
              onNavigate={() => setMobileOpen(false)}
            />
            <li className="w-full text-center">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={demoOpen}
                aria-controls="demo-menu-mobile"
                onClick={() => setDemoOpen((o) => !o)}
                className={`inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-base no-underline transition-colors duration-200 ${
                  demoActive
                    ? "text-accent"
                    : "text-foreground hover:text-accent"
                }`}
              >
                Demo
                <ChevronDown
                  aria-hidden
                  className={`size-[1em] shrink-0 transition-transform duration-200 ${
                    demoOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
              {demoOpen ? (
                <ul
                  id="demo-menu-mobile"
                  className="m-0 mt-3 flex list-none flex-col items-stretch gap-2 p-0 pl-4"
                >
                  {DEMO_LINKS.map(({ label, href }) => (
                    <li key={href} className="w-full text-center">
                      <Link
                        href={href}
                        onClick={() => {
                          setMobileOpen(false);
                          setDemoOpen(false);
                        }}
                        className="block px-4 py-2 text-base text-foreground no-underline transition-colors hover:text-accent"
                      >
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
            <NavLinks
              links={[CONTRIBUTORS_LINK]}
              pathname={pathname}
              centerOnMobile
              onNavigate={() => setMobileOpen(false)}
            />
            <li className="w-full text-center">
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={docsOpen}
                aria-controls="docs-menu-mobile"
                onClick={() => setDocsOpen((o) => !o)}
                className={`inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-base no-underline transition-colors duration-200 ${
                  docsActive
                    ? "text-accent"
                    : "text-foreground hover:text-accent"
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
                <ul
                  id="docs-menu-mobile"
                  className="m-0 mt-3 flex list-none flex-col items-stretch gap-2 p-0 pl-4"
                >
                  {DOC_LINKS.map(({ label, href }) => (
                    <li key={href} className="w-full text-center">
                      <Link
                        href={href}
                        onClick={() => {
                          setMobileOpen(false);
                          setDocsOpen(false);
                        }}
                        className="block px-4 py-2 text-base text-foreground no-underline transition-colors hover:text-accent"
                      >
                        {label}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          </ul>
        </div>
      ) : null}
    </header>
  );
}
