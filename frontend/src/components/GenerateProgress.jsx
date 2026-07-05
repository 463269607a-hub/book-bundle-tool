export default function GenerateProgress({ generating, progress }) {
  if (!generating) return null
  const pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0
  return (
    <div className="progress-text">
      <div>生成中... {progress.current}/{progress.total}</div>
      <div style={{ marginTop: 6, width: 260, height: 8, background: '#e9ecef', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: '#28a745', transition: 'width .3s' }} />
      </div>
    </div>
  )
}
