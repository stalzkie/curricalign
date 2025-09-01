'use client';

import { JSX, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {
  RiDashboardLine,
  RiUser3Line,
  RiDatabase2Line,
  RiLogoutBoxRLine,
  RiBook2Line,
} from 'react-icons/ri';

/** Gradient outlined 4-point star with hover animation */
function StarBurstIcon({ className = '' }: { className?: string }) {
  const id = 'grad-green-star';
  return (
    <svg
      viewBox="0 0 24 24"
      className={className + ' transition-transform duration-300 ease-out group-hover:rotate-12 group-hover:scale-110'}
      fill="none"
      stroke={`url(#${id})`}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <defs>
        <linearGradient id={id} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#10e7ffff" />   {/* green-600 */}
          <stop offset="100%" stopColor="#22c55e" /> {/* green-500 */}
        </linearGradient>
      </defs>
      {/* 4-point star (diamond style with extra mid points for a crisp outline) */}
      <polygon
        points="12,2 14.5,9.5 22,12 14.5,14.5 12,22 9.5,14.5 2,12 9.5,9.5"
        fill="none"
      />
    </svg>
  );
}

interface SidebarItem {
  name: string;
  href: string;
  icon: JSX.Element;
  special?: boolean; // for the animated star
}

const sidebarItems: SidebarItem[] = [
  { name: 'Dashboard', href: '/', icon: <RiDashboardLine /> },
  { name: 'Account', href: '/account', icon: <RiUser3Line /> },
  { name: 'Database', href: '/database', icon: <RiDatabase2Line /> },
  {
    name: 'Generate Report',
    href: '/report',
    icon: <StarBurstIcon className="h-[22px] w-[22px]" />,
    special: true,
  },
  // Removed "Help"
  { name: 'Logout', href: '/logout', icon: <RiLogoutBoxRLine /> },
];

export default function Sidebar() {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div
      className={`fixed left-0 top-0 h-full btn_border_silver transition-all duration-300 ease-in-out z-50 ${
        isExpanded ? 'w-64' : 'w-16'
      }`}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
      aria-label="Sidebar"
    >
      <div className="card_background h-full rounded-r">
        {/* Logo / Brand */}
        <div className="flex items-center justify-center h-16 border-b border-gray-200">
          <Link
            href="/"
            className="inline-flex items-center justify-center"
            style={{ color: '#388e3c)' }}
            aria-label="Go to Dashboard"
          >
            {isExpanded ? (
              <Image
                src="/logo-wordmark.svg"
                alt="CurricAlign"
                width={140}
                height={28}
                priority
              />
            ) : (
              <Image
                src="/logo-mark.svg"
                alt="CurricAlign"
                width={24}
                height={24}
                priority
              />
            )}
          </Link>
        </div>

        {/* Nav */}
        <nav className="mt-8">
          <ul className="space-y-2">
            {sidebarItems.map((item) => (
              <li key={item.name}>
                <Link
                  href={item.href}
                  className={`
                    group flex items-center px-4 py-3 transition-all duration-200
                    text_secondaryColor hover:text_defaultColor
                    ${item.special ? 'hover:bg-transparent' : 'hover:bg-gray-100'}
                  `}
                >
                  {/* Icon (no box) */}
                  <span
                    className={`mr-3 leading-none shrink-0 ${
                      item.special
                        ? 'drop-shadow-none group-hover:drop-shadow-[0_0_6px_rgba(34,197,94,0.55)]'
                        : ''
                    }`}
                    style={{ color: item.special ? 'transparent' : '#388e3c)' }}
                    aria-hidden="true"
                  >
                    {/* For the star we supply full SVG; others use react-icons */}
                    {item.special ? <StarBurstIcon className="h-[22px] w-[22px]" /> : <span className="text-xl">{item.icon}</span>}
                  </span>

                  <span
                    className={`transition-all duration-300 whitespace-nowrap ${
                      isExpanded
                        ? 'opacity-100 translate-x-0'
                        : 'opacity-0 -translate-x-4 group-hover:opacity-100 group-hover:translate-x-0'
                    }`}
                  >
                    {item.name}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {/* Footer message */}
        <div className="absolute bottom-4 left-0 right-0 px-4">
          {isExpanded && (
            <div className="text-xs text_triaryColor text-center transition-opacity">
              Welcome back!
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
