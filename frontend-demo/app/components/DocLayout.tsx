interface DocLayoutProps {
  children: React.ReactNode;
}

export function DocLayout({ children }: DocLayoutProps) {
  return (
    <div className="mx-auto w-full max-w-[720px] px-6 py-16 md:py-20">
      {children}
    </div>
  );
}
