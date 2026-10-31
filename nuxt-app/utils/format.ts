export type Guide = Record<string, any>

export interface GuideEntry {
  key: string
  dir: string
  stem: string
  name: string
  website: string
  summary: string
  approval: string
  mode: string
  model: string
  generated_at: string
  start: string
  public: string
  tested: number
  claims: number
  retested: { ok: number; checked: number } | null
  mtime: number
}

// Display helpers shared by the sidebar, library and guide pages
export const GUIDE_SECTIONS: [string, string, string][] = [
  ['sec-1', '📊', 'Difficulty & time'], ['sec-2', '🪜', 'Path to public'], ['sec-3', '🛠', 'Steps'], ['sec-4', '📋', 'What you need'],
  ['sec-5', '⚠️', 'Risks'], ['sec-6', '🤝', 'Who does what'], ['sec-7', '🔎', 'Trust & sources']
]
const AVATAR_COLORS = ['#e11d48', '#7c3aed', '#2563eb', '#0891b2', '#059669', '#d97706', '#db2777', '#4f46e5']
export const avatarColor = (name: string) => AVATAR_COLORS[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_COLORS.length]

export const LABELS: Record<string, string> = { tested: 'Tested', official_docs: 'Official docs', inferred: 'Inferred', unknown: 'Unknown' }
export const LABEL_HELP: Record<string, string> = {
  tested: 'Someone tried it and saw the result: a person (manual test) or the agent (live probe).',
  official_docs: "Stated in the provider's docs or portal.",
  inferred: 'Reasoned from other facts; the basis is shown.',
  unknown: 'Looked for and not found, or not checked.'
}
export const SOURCE_TYPES: Record<string, string> = { docs: 'Provider docs', portal_text: 'Provider portal text', manual_test: 'Manual test', agent_probe: 'Agent live probe', none: 'No source' }
export const TESTED_TITLE = 'Tested live by the agent'
export const LEVELS: Record<string, string> = { easy: 'Easy', medium: 'Medium', hard: 'Hard', unknown: 'Unknown' }
export const STATUS: Record<string, string> = { required: 'Required', optional: 'Optional', not_asked: 'Not asked', unknown: 'Unknown' }
export const ACTOR: Record<string, string> = { human: 'You', agent: 'Agent', both: 'Both' }
export const SOURCE_KIND: Record<string, string> = { docs: 'Docs', portal: 'Portal', manual_test: 'Manual test' }

export const SECTION_NAMES: Record<string, string> = {
  difficulty: 'Difficulty', time: 'Time', setup_types: 'Setup types', creation_paths: 'Creation paths',
  access_ladder: 'Access ladder', requirements: 'Requirements', limits: 'Limits', blockers: 'Blockers',
  steps: 'Steps', agent_vs_human: 'Agent vs you', extras: 'Also worth knowing'
}

export const safeUrl = (u?: string) => (/^https?:\/\//i.test(u || '') ? (u as string) : null)
export const hostOf = (u?: string) => {
  try { return new URL(u || '').host } catch { return u || '' }
}

export interface FlatClaim { where: string; claim: Record<string, any> }

function collect(node: any, where: string, out: FlatClaim[]) {
  if (Array.isArray(node)) return node.forEach((n) => collect(n, where, out))
  if (node && typeof node === 'object') {
    if (node.label && node.checked_at && node.text) return void out.push({ where, claim: node })
    for (const k of Object.keys(node)) collect(node[k], where || k, out)
  }
}

// Every claim in the guide with the section it sits in.
export function allClaims(g: Guide): FlatClaim[] {
  const out: FlatClaim[] = []
  for (const k of Object.keys(SECTION_NAMES)) if (g[k]) collect(g[k], SECTION_NAMES[k], out)
  return out
}

export function claimCounts(claims: FlatClaim[]) {
  const c: Record<string, number> = { tested: 0, official_docs: 0, inferred: 0, unknown: 0 }
  claims.forEach((x) => { c[x.claim.label] = (c[x.claim.label] || 0) + 1 })
  return c
}
