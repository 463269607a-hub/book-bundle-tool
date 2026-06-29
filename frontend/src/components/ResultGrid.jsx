export default function ResultGrid({ results, sessionId }) {
  if (!results || results.length === 0) return null

  function downloadOne(result) {
    const byteStr = atob(result.image_b64)
    const arr = new Uint8Array(byteStr.length)
    for (let i = 0; i < byteStr.length; i++) arr[i] = byteStr.charCodeAt(i)
    const blob = new Blob([arr], { type: 'image/jpeg' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${result.output_name}.jpg`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="match-summary" style={{ marginBottom: 16 }}>
        <span className="badge badge-green">已生成 {results.length} 张</span>
      </div>
      <div className="results-grid">
        {results.map((r, i) => (
          <div className="result-card" key={i}>
            <img
              src={`data:image/jpeg;base64,${r.image_b64}`}
              alt={r.output_name}
            />
            <div className="result-card-footer">
              <div className="result-name">{r.output_name}</div>
              <button className="btn btn-primary" onClick={() => downloadOne(r)}>
                下载
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
