import { useRef, useState } from 'react'

export default function UploadTable({ sessionId, onUploaded }) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [count, setCount] = useState(0)
  const [filename, setFilename] = useState('')
  const inputRef = useRef()

  async function handleFile(file) {
    if (!file) return
    setUploading(true)
    setFilename(file.name)
    const fd = new FormData()
    fd.append('session_id', sessionId)
    fd.append('file', file)
    try {
      const res = await fetch('/api/upload/table', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) {
        alert('上传表格失败：' + (data.detail || JSON.stringify(data)))
        return
      }
      setCount(data.count)
      onUploaded(data.count, data.rows)
    } catch (e) {
      alert('上传表格失败：' + e.message)
    } finally {
      setUploading(false)
    }
  }

  function onInputChange(e) {
    handleFile(e.target.files[0])
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files[0])
  }

  function downloadTemplate() {
    const bom = '﻿'
    const header = 'group_id,output_name,code_1,code_2,code_3,code_4,code_5'
    const rows = [
      'set001,二本套装示例,29412867,29412868,,,',
      'set002,三本套装示例,29412867,29412868,29412869,,',
      'set003,四本套装示例,29412867,29412868,29412869,29412870,',
      'set004,五本套装示例,29412867,29412868,29412869,29412870,29412871',
    ]
    const csv = bom + [header, ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '组合表模板.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    <button
      className="btn btn-secondary"
      style={{ alignSelf: 'flex-start', fontSize: 13 }}
      onClick={(e) => { e.stopPropagation(); downloadTemplate() }}
    >
      ↓ 下载表格模板
    </button>
    <div
      className={`upload-area${dragOver ? ' drag-over' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        onChange={onInputChange}
        style={{ display: 'none' }}
      />
      <div className="upload-icon">📋</div>
      <div className="upload-label">上传匹配表格</div>
      <div className="upload-hint">拖拽或点击选择 CSV / Excel 文件</div>
      <div className="upload-hint" style={{ marginTop: 4 }}>列名：group_id, output_name, code_1 ~ code_5</div>
      {uploading && <div className="upload-count" style={{ background: '#fff3cd', color: '#856404' }}>上传中...</div>}
      {!uploading && count > 0 && (
        <div className="upload-count">{filename} — 共 {count} 行</div>
      )}
    </div>
    </div>
  )
}
