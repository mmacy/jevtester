// The top-level views, in tab order. Each has a URL so a view can be linked
// and reloaded.
export interface ViewDef {
  path: string
  label: string
}

export const VIEWS: readonly ViewDef[] = [
  { path: '/compare', label: 'Compare' },
  { path: '/suites', label: 'Suites' },
  { path: '/runs', label: 'Runs' },
  { path: '/question-sets', label: 'Question sets' },
  { path: '/policies', label: 'Policies' },
  { path: '/probes', label: 'Probes' },
  { path: '/targets', label: 'Targets' },
]
