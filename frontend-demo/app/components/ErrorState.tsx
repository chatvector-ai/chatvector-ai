"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

type Props = {
  kicker?: string; // defaults to "// error"
  heading: string;
  message: string;
  onRetry?: () => void; // renders a retry button when provided
};

export default function ErrorState({
  kicker = "// error",
  heading,
  message,
  onRetry,
}: Props) {
  const [logo, setLogo] = useState("/redirect-logo-dark.svg");

  useEffect(() => {
    const update = () => {
      const theme = document.documentElement.getAttribute("data-theme");
      setLogo(theme === "light" ? "/redirect-logo-light.svg" : "/redirect-logo-dark.svg");
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex flex-col items-center text-center gap-3">
      <Image
        src={logo}
        alt="Error logo"
        width={80}
        height={80}
        priority
      />
      <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        {kicker}
      </p>
      <h2 className="text-foreground font-semibold text-xl">{heading}</h2>
      <p className="text-muted text-[1rem]">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 border border-border bg-transparent hover:bg-surface text-foreground rounded-lg px-5 py-2 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
