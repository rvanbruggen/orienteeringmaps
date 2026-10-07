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

/** 8793.8 -> "8,8 km" */
export const fmtDistance = (m) => (m || m === 0 ? `${(m / 1000).toFixed(1).replace('.', ',')} km` : '')

/** 4124 -> "1:08:44", 1800 -> "30:00" */
export function fmtDuration(s) {
  if (!s && s !== 0) return ''
  const h = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = Math.round(s % 60)
  const two = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${two(mm)}:${two(ss)}` : `${mm}:${two(ss)}`
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

/** Public site publish levels (see backend/app/publish.py). */
export const PUBLISH_LEVELS = [
  { value: 'private', label: 'Private', hint: 'Not on the public site' },
  { value: 'outline', label: 'Outline', hint: 'Details, events and where the map is; no images' },
  { value: 'overlay', label: 'Overlay', hint: 'Plus the main map image, placed on the aerial photo' },
  { value: 'full', label: 'Full', hint: 'Plus every page and course print, and the original files to download' },
]
