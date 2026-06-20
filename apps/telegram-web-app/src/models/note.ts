export type NoteKind = 'daily' | 'weekly'

export interface NoteListItem {
  id: string
  sort_key: string
  kind: NoteKind
  title: string
  has_photos: boolean
  snippet: string
}

export interface NoteDetail {
  id: string
  kind: NoteKind
  sort_key: string
  frontmatter: Record<string, unknown>
  markdown: string
}

export interface FeaturedNote {
  id: string
  title: string
  markdown: string
  source: string
}
