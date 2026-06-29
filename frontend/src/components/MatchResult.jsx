export default function MatchResult({ validationResult }) {
  if (!validationResult) return null
  const { generatable, failed } = validationResult

  return (
    <div>
      <div className="match-summary">
        <span className="badge badge-green">可生成 {generatable.length} 条</span>
        {failed.length > 0 && (
          <span className="badge badge-red">验证失败 {failed.length} 条</span>
        )}
      </div>
      {failed.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>group_id</th>
              <th>output_name</th>
              <th>失败原因</th>
            </tr>
          </thead>
          <tbody>
            {failed.map((item, i) => (
              <tr key={i}>
                <td>{item.row?.group_id || '-'}</td>
                <td>{item.row?.output_name || '-'}</td>
                <td className="reason-cell">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
