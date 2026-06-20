import { useMemo } from 'react'
import type { ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { isImageEmbed, mediaUrlForEmbed } from '../obsidian'

interface NoteMarkdownProps {
  noteId: string
  markdown: string
  onToggle: (line: number, checked: boolean) => void
}

const WIKILINK_HREF = '#wikilink'

/**
 * Pre-process Obsidian-flavoured markdown into standard markdown that
 * react-markdown (v9 + remark-gfm) can render directly.
 *
 * - `![[file.jpg]]` image embeds  -> `![](<media url>)`
 * - `![[file]]` non-image embeds  -> plain filename text
 * - `[[target|label]]` wikilinks  -> `[label](#wikilink)` (rendered as an
 *   inert chip via the `a` component override)
 */
function preprocess(markdown: string, noteId: string): string {
  // Image / file embeds: ![[...]]
  let out = markdown.replace(/!\[\[([^\]]+)\]\]/g, (_m, inner: string) => {
    const file = inner.trim()
    if (isImageEmbed(file)) {
      // Angle-bracket destination keeps spaces in filenames from truncating the URL.
      return `![](<${mediaUrlForEmbed(file, noteId)}>)`
    }
    return file
  })

  // Wikilinks: [[target|label]] or [[label]]
  out = out.replace(/\[\[([^\]]+)\]\]/g, (_m, inner: string) => {
    const label = inner.includes('|') ? inner.split('|').pop()!.trim() : inner.trim()
    return `[${label}](${WIKILINK_HREF})`
  })

  return out
}

type MdNode = {
  position?: { start?: { line?: number } }
  children?: Array<{
    tagName?: string
    properties?: { type?: string; checked?: boolean }
  }>
}

export default function NoteMarkdown({ noteId, markdown, onToggle }: NoteMarkdownProps) {
  const processed = useMemo(() => preprocess(markdown, noteId), [markdown, noteId])

  return (
    <div className="tm-note-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img(props) {
            const { src, alt } = props
            const url = typeof src === 'string' ? src : undefined
            // Empty alt drops the implicit "img" role; fall back to the
            // filename so the image stays an accessible, queryable element.
            const altText = alt && alt.length > 0 ? alt : url ? url.split('/').pop() ?? '' : ''
            return <img className="tm-img" src={url} alt={altText} />
          },
          // The sentinel href `#wikilink` is what makes wikilinks non-navigable:
          // only those links become inert chips; real hrefs pass through as anchors.
          a(props) {
            const { href, children } = props
            if (href === WIKILINK_HREF) {
              return <span className="tm-wikilink">{children}</span>
            }
            return <a href={href} target="_blank" rel="noreferrer">{children}</a>
          },
          // Suppress remark-gfm's default (disabled) task-list checkbox; we
          // render our own interactive one inside the `li` override.
          input() {
            return null
          },
          li(props) {
            const { node, children, className, ...rest } = props as ComponentPropsWithoutRef<'li'> & {
              node?: MdNode
            }
            const isTask = typeof className === 'string' && className.includes('task-list-item')
            if (isTask && node) {
              const inputChild = node.children?.find(
                (c) => c.tagName === 'input' && c.properties?.type === 'checkbox',
              )
              const checked = Boolean(inputChild?.properties?.checked)
              const line = node.position?.start?.line
              return (
                <li {...rest} className={className}>
                  <input
                    type="checkbox"
                    className="tm-checkbox"
                    defaultChecked={checked}
                    onChange={(e) => {
                      if (typeof line === 'number') onToggle(line, e.currentTarget.checked)
                    }}
                  />
                  {children}
                </li>
              )
            }
            return (
              <li {...rest} className={className}>
                {children}
              </li>
            )
          },
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  )
}
