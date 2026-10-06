// App-wide cached data: enums, counts, clubs, version.
import { api } from './api.js'

export const meta = $state({ version: '', counts: {}, enums: { map_types: [], file_kinds: [], event_types: [], disciplines: [], standards: [] } })
export const clubs = $state({ list: [] })

export async function refreshMeta() {
  Object.assign(meta, await api.get('/api/meta'))
}

export async function refreshClubs() {
  clubs.list = await api.get('/api/clubs')
}

export const toast = $state({ message: '', kind: 'info', timer: null })

export function notify(message, kind = 'info') {
  clearTimeout(toast.timer)
  toast.message = message
  toast.kind = kind
  toast.timer = setTimeout(() => (toast.message = ''), kind === 'error' ? 7000 : 3500)
}
