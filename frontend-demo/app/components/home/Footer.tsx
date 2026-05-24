import Image from "next/image";
import { GITHUB_REPO } from "../../lib/constants";

const FOOTER_LINKS: { label: string; href: string; external?: boolean }[] = [
  { label: "GitHub", href: GITHUB_REPO, external: true },
  { label: "Docs", href: "#" },
  { label: "Roadmap", href: "#" },
  { label: "Issues", href: `${GITHUB_REPO}/issues`, external: true },
  {
    label: "License (MIT)",
    href: `${GITHUB_REPO}/blob/main/LICENSE`,
    external: true,
  },
];

export default function Footer() {
  return (
    <footer className="border-t border-border px-8 py-10">
      <div className="mx-auto flex max-w-[1100px] flex-col items-center gap-6 text-center md:flex-row md:flex-wrap md:justify-between md:text-left">
        <div className="flex items-center gap-1.5 font-mono font-bold md:gap-2">
          <Image
            src="/chatvector-logo-dark.svg"
            alt=""
            width={70}
            height={70}
            unoptimized
            className="size-9 shrink-0 [[data-theme=light]_&]:hidden"
          />
          <Image
            src="/chatvector-logo-light.svg"
            alt=""
            width={70}
            height={70}
            unoptimized
            className="hidden size-9 shrink-0 [[data-theme=light]_&]:block"
          />
          <span className="text-[1.2rem] bg-gradient-to-r from-accent to-blue bg-clip-text text-transparent">
            ChatVector
          </span>
        </div>
        <div className="flex flex-wrap justify-center gap-8 md:justify-start">
          {FOOTER_LINKS.map(({ label, href, external }) => (
            <a
              key={label}
              href={href}
              {...(external
                ? { target: "_blank", rel: "noopener noreferrer" }
                : {})}
              className="text-[0.93rem] text-muted no-underline transition-colors duration-200 hover:text-foreground"
            >
              {label}
            </a>
          ))}
        </div>
        <div className="text-[0.95rem] text-subtle">
          {"© 2026 ChatVector \u00B7 Open Source \u00B7 MIT"}
        </div>
      </div>
    </footer>
  );
}