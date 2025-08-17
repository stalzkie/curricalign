'use client';

import { PropsWithChildren, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

export default function ReactQueryProvider({ children }: PropsWithChildren) {
  // Create once per browser session
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Keep data “fresh” for 5 mins; navigating back within this window shows cached data instantly
            staleTime: 5 * 60 * 1000,
            // Keep cache in memory for 30 mins after unused
            gcTime: 30 * 60 * 1000,
            retry: 2, // fewer retries = snappier UX
            refetchOnWindowFocus: false, // avoid surprise refetches on tab focus
            refetchOnReconnect: true,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      {/* DevTools: toggle in dev only */}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
