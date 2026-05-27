import { describe, expect, it } from "vitest";
import { ForgerQueryProvider, createForgerQueryClient, forgerQueryKeys } from "../query";

describe("Forger Query helpers", () => {
  it("creates a conservative QueryClient and stable query keys", () => {
    const client = createForgerQueryClient();

    expect(client.getDefaultOptions().queries).toMatchObject({
      retry: 1,
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    });
    expect(client.getDefaultOptions().mutations).toMatchObject({ retry: 0 });
    expect(forgerQueryKeys.resource("status")).toEqual(["forger", "status"]);
    expect(ForgerQueryProvider({ children: "ok", client }).props.client).toBe(client);
    expect(ForgerQueryProvider({ children: "ok" }).props.client).toBeDefined();
  });
});
