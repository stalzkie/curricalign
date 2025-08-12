'use client';

import { useState } from 'react';
import Link from 'next/link';

interface SidebarItem {
  name: string;
  href: string;
  icon: string;
}

const sidebarItems: SidebarItem[] = [
  { name: 'Dashboard', href: '/', icon: '📊' },
  { name: 'Account', href: '/account', icon: '👤' },
  { name: 'Database', href: '/database', icon: '🗄️' },
  { name: 'Generate Report', href: '/report', icon: '📋' },
  { name: 'Help', href: '/help', icon: '❓' },
  { name: 'Logout', href: '/logout', icon: '🚪' },
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
    >
      <div className="card_background h-full">
        {/* Logo/Brand Section */}
        <div className="flex items-center justify-center h-16 border-b border-gray-300">
          <div className={`transition-all duration-300 ${isExpanded ? 'opacity-100' : 'opacity-0'}`}>
            {isExpanded && <span className="text-xl font-bold text_defaultColor">CurricAlign</span>}
          </div>
          {!isExpanded && <span className="text-2xl">📚</span>}
        </div>

      {/* Navigation Items */}
      <nav className="mt-8">
        <ul className="space-y-2">
          {sidebarItems.map((item) => (
            <li key={item.name}>
              <Link
                href={item.href}
                className="flex items-center px-4 py-3 text_secondaryColor hover:bg-gray-100 hover:text_defaultColor transition-colors duration-200 group"
              >
                <span className="text-xl mr-3">{item.icon}</span>
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

      {/* Footer/User Section */}
      <div className="absolute bottom-4 left-0 right-0 px-4">
        <div className={`transition-all duration-300 ${isExpanded ? 'opacity-100' : 'opacity-0'}`}>
          {isExpanded && (
            <div className="text-xs text_triaryColor text-center">
              Welcome back!
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
