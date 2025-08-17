'use client';

import { JSX, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {
  RiDashboardLine,
  RiUser3Line,
  RiDatabase2Line,
  RiFileChartLine,
  RiQuestionLine,
  RiLogoutBoxRLine,
  RiBook2Line
} from 'react-icons/ri';

interface SidebarItem {
  name: string;
  href: string;
  icon: JSX.Element;
}

const sidebarItems: SidebarItem[] = [
  { name: 'Dashboard',       href: '/',  icon: <RiDashboardLine /> },
  { name: 'Account',         href: '/account',    icon: <RiUser3Line /> },
  { name: 'Database',        href: '/database',   icon: <RiDatabase2Line /> },
  { name: 'Generate Report', href: '/report',     icon: <RiFileChartLine /> },
  { name: 'Help',            href: '/help',       icon: <RiQuestionLine /> },
  { name: 'Logout',          href: '/logout',     icon: <RiLogoutBoxRLine /> },
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
            style={{ color: 'var(--brand-teal, #025864)' }}
            aria-label="Go to Dashboard"
          >
            {isExpanded ? (
              // wordmark when expanded
              <Image
                src="/logo-wordmark.svg"
                alt="CurricAlign"
                width={140}
                height={28}
                priority
              />
            ) : (
              // square mark when collapsed
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
                  className="
                    group flex items-center px-4 py-3 transition-colors duration-200
                    text_secondaryColor hover:bg-gray-100 hover:text_defaultColor
                  "
                >
                  {/* Icon WITHOUT background/border box */}
                  <span
                    className="text-xl mr-3 leading-none shrink-0"
                    style={{ color: 'var(--brand-teal, #025864)' }}
                    aria-hidden="true"
                  >
                    {item.icon}
                  </span>

                  <span
                    className={`
                      transition-all duration-300 whitespace-nowrap
                      ${isExpanded
                        ? 'opacity-100 translate-x-0'
                        : 'opacity-0 -translate-x-4 group-hover:opacity-100 group-hover:translate-x-0'}
                    `}
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
