// Thin wrapper around fetch for the JSON API.

async function request(method, url, body) {
  const opts = { method, headers: {} }
  if (body instanceof FormData) {
    opts.body = body
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    let msg = data?.detail ?? res.statusText
    if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(1).join('.')}: ${d.msg}`).join('; ')
    throw new Error(msg)
  }
  return data
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body),
  patch: (url, body) => request('PATCH', url, body),
  del: (url) => request('DELETE', url),
}

/** Upload one file with progress callbacks: onProgress(fraction 0..1). Resolves to an UploadResult. */
export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/files')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
    xhr.upload.onload = () => onProgress?.(1)
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText)
        if (xhr.status >= 400) reject(new Error(data?.detail ?? xhr.statusText))
        else resolve(data[0])
      } catch {
        reject(new Error(`Upload failed (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new Error('Network error'))
    const fd = new FormData()
    fd.append('files', file, file.name)
    xhr.send(fd)
  })
}

/** Copy only the given keys (the API rejects unknown fields). */
export const pick = (obj, keys) => Object.fromEntries(keys.filter((k) => k in obj).map((k) => [k, obj[k] === '' ? null : obj[k]]))

export const MAP_KEYS = ['name', 'location', 'lat', 'lon', 'map_type', 'club_id', 'tags', 'notes', 'needs_review', 'publish_level', 'public_note']
export const VERSION_KEYS = ['label', 'survey_date', 'cartographer', 'scale', 'contour_interval', 'standard', 'notes']
export const EVENT_KEYS = ['name', 'date', 'end_date', 'event_type', 'discipline', 'organiser_club_id', 'results_url', 'notes', 'map_version_id']
export const COURSE_KEYS = ['name', 'length_km', 'climb_m', 'scale', 'controls', 'file_id', 'page_no', 'notes']
