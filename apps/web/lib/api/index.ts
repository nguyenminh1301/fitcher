// The api the app uses: each feature from the implementation lib/api/sources.ts names.

import type { Feature, FitcherApi } from "./client";
import { httpApi } from "./http";
import { createMockApi, type MockApi } from "./mock";
import { FEATURES, sources, type Sources } from "./sources";

export function createApi(current: Sources, mock: FitcherApi, http: FitcherApi): FitcherApi {
  return Object.fromEntries(FEATURES.map((feature: Feature) => [feature, current[feature] === "http" ? http[feature] : mock[feature]])) as unknown as FitcherApi;
}

export const mockApi: MockApi = createMockApi({ latencyMs: 250 });
export const api: FitcherApi = createApi(sources, mockApi, httpApi);
