import { useEffect, useState } from 'react'
import UploadImages from './components/UploadImages'
import UploadTable from './components/UploadTable'
import MatchResult from './components/MatchResult'
import GenerateProgress from './components/GenerateProgress'
import ResultGrid from './components/ResultGrid'
import FailureList from './components/FailureList'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [sessionError, setSessionError] = useState(false)
  const [imageCount, setImageCount] = useState(0)
  const [tableRows, setTableRows] = useState([])
  const [validationResult, setValidationResult] = useState(null)
  const [debugMode, setDebugMode] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generateProgress, setGenerateProgress] = useState({ current: 0, total: 0 })
  const [results, setResults] = useState([])
  const [allFailed, setAllFailed] = useState([])

  function createSession() {
    setSessionError(false)
    fetch('/api/session/create', { method: 'POST' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json() })
      .then(d => setSessionId(d.session_id))
      .catch(e => { console.error('Session create failed', e); setSessionError(true) })
  }

  // Create session on mount
  useEffect(() => { createSession() }, [])

  // 会话在服务器端丢失（如服务重启）：重置页面状态并自动重建会话
  function handleSessionExpired() {
    alert('会话已过期（服务器可能重启过），已自动新建会话，请重新上传图片和表格')
    setSessionId(null)
    setImageCount(0)
    setTableRows([])
    setValidationResult(null)
    setResults([])
    setAllFailed([])
    createSession()
  }

  function handleImagesUploaded(count) {
    setImageCount(count)
    // Reset validation when images change
    setValidationResult(null)
    setResults([])
    setAllFailed([])
  }

  function handleTableUploaded(count, rows) {
    setTableRows(rows)
    // Reset validation when table changes
    setValidationResult(null)
    setResults([])
    setAllFailed([])
  }

  async function handleValidate() {
    if (!sessionId) return
    try {
      const res = await fetch('/api/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      })
      if (res.status === 404) { handleSessionExpired(); return }
      const data = await res.json()
      setValidationResult(data)
      setResults([])
      setAllFailed([])
    } catch (e) {
      alert('验证失败：' + e.message)
    }
  }

  async function handleGenerate() {
    if (!sessionId || !validationResult) return
    setGenerating(true)
    setGenerateProgress({ current: 0, total: validationResult.generatable.length })
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, debug: debugMode }),
      })
      if (res.status === 404) { handleSessionExpired(); return }
      const data = await res.json()
      setResults(data.results || [])
      setAllFailed(data.failed || [])
      setGenerateProgress({ current: data.results?.length || 0, total: validationResult.generatable.length })
    } catch (e) {
      alert('生成失败：' + e.message)
    } finally {
      setGenerating(false)
    }
  }

  async function handleDownloadZip() {
    if (!sessionId) return
    try {
      const res = await fetch('/api/download/zip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      })
      if (res.status === 404) { handleSessionExpired(); return }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'book_bundles.zip'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('下载失败：' + e.message)
    }
  }

  const canValidate = sessionId && imageCount > 0 && tableRows.length > 0
  const canGenerate = validationResult && validationResult.generatable.length > 0 && !generating

  return (
    <div className="app">
      {/* Header */}
      <div className="app-header">
        <h1>图书套装主图批量生成工具</h1>
        <p>上传书籍封面图片及匹配表格，批量合成套装主图</p>
      </div>

      {/* Upload Section */}
      <div className="card">
        <div className="card-title">第一步：上传文件</div>
        {sessionId ? (
          <div className="upload-row">
            <UploadImages sessionId={sessionId} onUploaded={handleImagesUploaded} onSessionExpired={handleSessionExpired} />
            <UploadTable sessionId={sessionId} onUploaded={handleTableUploaded} onSessionExpired={handleSessionExpired} />
          </div>
        ) : (
          sessionError ? (
            <div style={{color:'#c00'}}>
              后端连接失败，请确认后端服务已启动（端口 8000）。
              <button className="btn btn-primary" style={{marginLeft:12}} onClick={createSession}>重试</button>
            </div>
          ) : (
            <div className="text-muted text-sm">正在初始化会话...</div>
          )
        )}
      </div>

      {/* Validate Section */}
      <div className="card">
        <div className="card-title">第二步：检查匹配</div>
        <div className="action-bar">
          <button
            className="btn btn-primary"
            onClick={handleValidate}
            disabled={!canValidate}
          >
            检查匹配
          </button>
          {!canValidate && (
            <span className="text-muted text-sm">请先上传图片和表格</span>
          )}
        </div>
        {validationResult && (
          <div className="mt-16">
            <MatchResult validationResult={validationResult} />
          </div>
        )}
      </div>

      {/* Generate Section */}
      <div className="card">
        <div className="card-title">第三步：生成图片</div>
        <div className="action-bar">
          <button
            className="btn btn-success"
            onClick={handleGenerate}
            disabled={!canGenerate}
          >
            开始生成
          </button>
        </div>
        <GenerateProgress generating={generating} progress={generateProgress} />
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div className="card">
          <div className="card-title">生成结果</div>
          <ResultGrid results={results} sessionId={sessionId} />
          <div className="download-all-bar mt-16">
            <button className="btn btn-primary" onClick={handleDownloadZip}>
              下载全部 ZIP
            </button>
          </div>
        </div>
      )}

      {/* Failure List */}
      {allFailed.length > 0 && (
        <div className="card">
          <div className="card-title">失败列表</div>
          <FailureList failed={allFailed} />
        </div>
      )}
    </div>
  )
}
