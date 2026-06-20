import { describe, it, expect } from 'vitest'
import { mediaUrlForEmbed, parseWikiEmbed, parseWikiLink } from '../obsidian'

describe('obsidian transforms', () => {
  it('builds a media url from an image embed + note date', () => {
    expect(mediaUrlForEmbed('photo_2026-05-21.jpg', '2026-05-21'))
      .toContain('/media/2026-05-21/photo_2026-05-21.jpg')
  })

  it('detects an image embed token', () => {
    expect(parseWikiEmbed('![[p.jpg]]')).toEqual({ file: 'p.jpg' })
    expect(parseWikiEmbed('![[note]]')).toEqual({ file: 'note' })
    expect(parseWikiEmbed('not an embed')).toBeNull()
  })

  it('parses a wikilink to its label', () => {
    expect(parseWikiLink('[[Mount Carmel]]')).toEqual({ label: 'Mount Carmel' })
    expect(parseWikiLink('[[a|b]]')).toEqual({ label: 'b' })
    expect(parseWikiLink('plain')).toBeNull()
  })
})
