export default function SeverityBadge({ severity }) {
  const cls = {
    error:   'badge-error',
    warning: 'badge-warning',
    info:    'badge-info',
  }[severity] ?? 'badge-info'

  return <span className={cls}>{severity}</span>
}
