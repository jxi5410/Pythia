'use client';

import { RunStoreProvider } from '@/lib/run-store';
import NavHeader from '@/components/NavHeader';

export default function StoreWrapper({ children }: { children: React.ReactNode }) {
  return (
    <RunStoreProvider>
      <NavHeader />
      {children}
    </RunStoreProvider>
  );
}
