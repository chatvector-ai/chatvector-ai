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
      <div className="mx-auto flex max-w-[1100px] flex-wrap items-center justify-between gap-6">
        <div className="font-mono text-[1.2rem] font-bold text-accent">
        <span className="bg-gradient-to-r from-accent to-blue bg-clip-text text-transparent">
            ChatVector
          </span>
        </div>
        <div className="flex flex-wrap gap-8">
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
        {/* --subtle is dimmer than --muted but still readable on --background (unlike --border) */}
        <div className="text-[0.95rem] text-subtle">
          © 2026 ChatVector · Open Source · MIT
        </div>
      </div>
    </footer>
  );
}
