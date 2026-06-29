export default function GenerateProgress({ generating, progress }) {
  if (!generating) return null
  return (
    <div className="progress-text">
      生成中... {progress.current}/{progress.total}
    </div>
  )
}
