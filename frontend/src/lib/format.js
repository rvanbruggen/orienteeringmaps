const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const thin = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

export const fmtScale = (n) => (n ? `1:${thin(n)}` : '')
export const fmtContour = (v) => (v || v === 0 ? `${+v} m` : '')
export const fmtKm = (v) => (v || v === 0 ? `${String(+v).replace('.', ',')} km` : '')

/** "2021" | "2021-05" | "2021-05-14" -> "2021" | "May 2021" | "14 May 2021" */
export function fmtDate(d) {
  if (!d) return ''
  const [y, m, day] = d.split('-')
  if (!m) return y
  if (!day) return `${MONTHS[+m - 1]} ${y}`
  return `${+day} ${MONTHS[+m - 1]} ${y}`
}

export function fmtBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 ** 2).toFixed(1)} MB`
}

export function yearsAgo(d) {
  if (!d) return null
  const [y, m = '06'] = d.split('-')
  const then = new Date(+y, +m - 1, 1)
  return (Date.now() - then.getTime()) / (365.25 * 24 * 3600 * 1000)
}

export const label = (s) => (s ? s.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()) : '')

/** Partial ISO date validation, same rule as the backend. */
export const isPartialDate = (s) => !s || /^\d{4}(-\d{2}(-\d{2})?)?$/.test(s)

/** Parse a scale typed as "1:10000", "1/7.500", "10 000" or "10000". */
export function parseScale(s) {
  if (s === null || s === undefined || s === '') return null
  const digits = String(s).replace(/^\s*1\s*[:/]\s*/, '').replace(/[^\d]/g, '')
  return digits ? parseInt(digits, 10) : null
}
