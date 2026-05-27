import { createElement, type ReactElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export const createForgerQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 5_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  });

export const forgerQueryKeys = {
  all: ["forger"] as const,
  resource: (...parts: readonly unknown[]) => [...forgerQueryKeys.all, ...parts] as const,
};

const defaultForgerQueryClient = createForgerQueryClient();

export function ForgerQueryProvider({
  children,
  client,
}: {
  children: ReactNode;
  client?: QueryClient;
}): ReactElement {
  return createElement(QueryClientProvider, { client: client ?? defaultForgerQueryClient }, children);
}
