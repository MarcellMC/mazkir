interface Props { visible: boolean; onClick: () => void }
export default function BackToTopFab({ visible, onClick }: Props) {
  if (!visible) return null
  return <button className="tm-fab" aria-label="Back to top" onClick={onClick}>↑</button>
}
