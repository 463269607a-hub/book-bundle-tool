export default function FailureList({ failed }) {
  if (!failed || failed.length === 0) return null

  function exportCSV() {
    const header = '组套名称,失败原因\n'
    const rows = failed.map(item => {
      const oname = (item.row?.output_name || '').toString().replace(/"/g, '""')
      const reason = (item.reason || '').replace(/"/g, '""')
      return `"${oname}","${reason}"`
    }).join('\n')
    const csv = '﻿' + header + rows  // BOM for Excel
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '失败列表.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="failure-header">
        <span className="badge badge-red">失败 {failed.length} 条</span>
        <button className="btn btn-secondary" onClick={exportCSV}>
          导出失败列表
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>组套名称</th>
            <th>失败原因</th>
          </tr>
        </thead>
        <tbody>
          {failed.map((item, i) => (
            <tr key={i}>
              <td>{item.row?.output_name || '-'}</td>
              <td className="reason-cell">{item.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
