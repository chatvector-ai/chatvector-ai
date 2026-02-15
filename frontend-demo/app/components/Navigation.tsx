import Link from "next/link"

export default function Navigation() {
  return (
    <nav className="
    flex justify-center 
    gap-8 px-6 py-6 
    font-black 
    bg-gradient-to-b from-slate-950 to-slate-900/20 border-b border-none
    text-white 
    sticky top-0 z-50">
      <Link
        href="/"
        className="transition-colors duration-200 hover:text-blue-400"
      >
        Home
      </Link>
      <Link
        href="/chat"
        className="transition-colors duration-200 hover:text-blue-400"
      >
        Chat
      </Link>
    </nav>
  )
}
