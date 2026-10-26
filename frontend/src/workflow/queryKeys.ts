export const sessionQueryKeys = {
  session: (sessionId: string) => ['session', sessionId] as const,
  candidates: (sessionId: string) => ['candidates', sessionId] as const,
  preview: (sessionId: string) => ['preview', sessionId] as const,
  productSearch: (sessionId: string) => ['product-search', sessionId] as const,
  suggestions: (sessionId: string, candidateId: string) =>
    ['suggestions', sessionId, candidateId] as const,
  mappings: (supplierKey: string) => ['mappings', supplierKey] as const,
  suppliers: ['suppliers'] as const,
  settings: ['settings'] as const,
  export: (sessionId: string) => ['export', sessionId] as const,
  review: (sessionId: string) => ['review', sessionId] as const,
}

export async function invalidateSessionData(
  queryClient: {
    invalidateQueries: (opts: { queryKey: readonly unknown[] }) => Promise<unknown>
  },
  sessionId: string,
  supplierKey?: string | null,
) {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: sessionQueryKeys.session(sessionId),
    }),
    queryClient.invalidateQueries({
      queryKey: sessionQueryKeys.candidates(sessionId),
    }),
    queryClient.invalidateQueries({
      queryKey: sessionQueryKeys.preview(sessionId),
    }),
    queryClient.invalidateQueries({
      queryKey: sessionQueryKeys.productSearch(sessionId),
    }),
    supplierKey
      ? queryClient.invalidateQueries({
          queryKey: sessionQueryKeys.mappings(supplierKey),
        })
      : Promise.resolve(),
  ])
}
