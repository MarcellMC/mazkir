import { api } from '../../services/api'

const IMG_EXT = /\.(jpe?g|png|gif|webp|heic)$/i

export function parseWikiEmbed(text: string): { file: string } | null {
  const m = text.match(/^!\[\[([^\]]+)\]\]$/)
  return m ? { file: m[1]!.trim() } : null
}

export function parseWikiLink(text: string): { label: string } | null {
  const m = text.match(/^\[\[([^\]]+)\]\]$/)
  if (!m) return null
  const inner = m[1]!
  const label = inner.includes('|') ? inner.split('|').pop()!.trim() : inner.trim()
  return { label }
}

export function isImageEmbed(file: string): boolean {
  return IMG_EXT.test(file)
}

export function mediaUrlForEmbed(file: string, noteDate: string): string {
  return api.getMediaUrl(noteDate, file)
}
