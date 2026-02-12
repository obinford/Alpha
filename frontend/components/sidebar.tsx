"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/ev-scanner", label: "EV Scanner" },
  { href: "/picks", label: "Picks" },
  { href: "/performance", label: "Performance" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-64 flex-col border-r border-gray-800 bg-gray-950 p-6">
      <Link href="/" className="mb-8 text-xl font-bold">
        RTM Picks
      </Link>
      <nav className="flex flex-col gap-1">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-lg px-4 py-2 text-sm transition-colors ${
              pathname === item.href
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:bg-gray-900 hover:text-white"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
