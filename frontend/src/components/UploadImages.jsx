import { useRef, useState } from 'react'

export default function UploadImages({ sessionId, onUploaded }) {
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [count, setCount] = useState(0)
  const inputRef = useRef()

  async function handleFiles(files) {
    if (!files || files.length === 0) return
    setUploading(true)
    const fd = new FormData()
    fd.append('session_id', sessionId)
    for (const f of files) {
      fd.append('files', f)
    }
    try {
      const res = await fetch('/api/upload/images', { method: 'POST', body: fd })
      const data = await res.json()
      setCount(data.count)
      onUploaded(data.count)
    } catch (e) {
      alert('上传图片失败：' + e.message)
    } finally {
      setUploading(false)
    }
  }

  function onInputChange(e) {
    handleFiles(e.target.files)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }

  return (
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
        accept=".jpg,.jpeg"
        multiple
        onChange={onInputChange}
        style={{ display: 'none' }}
      />
      <div className="upload-icon">🖼️</div>
      <div className="upload-label">上传书籍图片</div>
      <div className="upload-hint">拖拽或点击选择 JPG 图片（可多选）</div>
      <div className="upload-hint" style={{ marginTop: 4 }}>文件名须以数字编码开头，如：9787010123456.jpg</div>
      {uploading && <div className="upload-count" style={{ background: '#fff3cd', color: '#856404' }}>上传中...</div>}
      {!uploading && count > 0 && (
        <div className="upload-count">已上传 {count} 张图片</div>
      )}
    </div>
  )
}
