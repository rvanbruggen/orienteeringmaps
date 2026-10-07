// GPS routes of your runs: loading, pace and colouring.
import { api } from './api.js'

const cache = new Map()

/** {latlng, time, distance, altitude} of a Strava activity (fetched once per page load). */
export function loadRoute(activityId) {
  if (!cache.has(activityId)) {
    const p = api.get(`/api/strava/activities/${activityId}/route`)
    p.catch(() => cache.delete(activityId))
    cache.set(activityId, p)
  }
  return cache.get(activityId)
}

const WINDOW_S = 10 // pace is smoothed over this many seconds either side

/** Pace (seconds per km) at each point, smoothed; null where there is no movement data. */
export function paces(route) {
  const { time: t, distance: d } = route
  const n = route.latlng.length
  if (!t?.length || !d?.length || t.length !== n || d.length !== n) return new Array(n).fill(null)
  const out = new Array(n)
  let lo = 0, hi = 0
  for (let i = 0; i < n; i++) {
    while (t[i] - t[lo] > WINDOW_S) lo++
    while (hi < n - 1 && t[hi + 1] - t[i] <= WINDOW_S) hi++
    const dt = t[hi] - t[lo], dd = d[hi] - d[lo]
    out[i] = dt > 0 && dd > 0 ? (dt / dd) * 1000 : Infinity
  }
  return out
}

export function median(values) {
  const v = values.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b)
  return v.length ? v[Math.floor(v.length / 2)] : null
}

/**
 * Your typical pace on the run: the median pace per metre covered. GPS watches record points
 * unevenly (more when slow or turning), so a plain median over points comes out too slow.
 */
export function typicalPace(route, pc = paces(route)) {
  const d = route.distance
  if (!d?.length || d.length !== pc.length) return median(pc)
  const items = []
  for (let i = 0; i < pc.length - 1; i++) {
    const w = d[i + 1] - d[i]
    if (w > 0 && Number.isFinite(pc[i])) items.push([pc[i], w])
  }
  if (!items.length) return null
  items.sort((a, b) => a[0] - b[0])
  const half = items.reduce((s, [, w]) => s + w, 0) / 2
  let acc = 0
  for (const [p, w] of items) if ((acc += w) >= half) return p
  return items[items.length - 1][0]
}

/** Colour for a pace relative to the run's median: green fast, yellow typical, red slow, dark red stopped. */
export function paceColour(pace, med) {
  if (pace == null || !med) return '#a626a4'
  if (!Number.isFinite(pace) || pace > med * 3) return '#7a0019'
  const r = Math.log(pace / med) / Math.log(1.8) // -1 = 1.8x faster, +1 = 1.8x slower
  const k = Math.max(-1, Math.min(1, r))
  const hue = Math.round((60 - 60 * k) / 10) * 10 // 120 green .. 60 yellow .. 0 red, in 13 steps
  return `hsl(${hue}, 85%, 42%)`
}

/**
 * Split a route into runs of points with (nearly) the same colour, for drawing as few polylines as possible.
 * project(lat, lon) gives the coordinates to draw at (lat/lon for a world map, pixels for the map image).
 */
export function colouredSegments(route, project, byPace = true) {
  const pts = route.latlng.map(([lat, lon]) => project(lat, lon))
  if (!byPace) return [{ colour: '#a626a4', points: pts }]
  const pc = paces(route)
  const med = typicalPace(route, pc)
  const out = []
  let cur = null
  for (let i = 0; i < pts.length; i++) {
    const colour = paceColour(pc[i], med)
    if (!cur || cur.colour !== colour) {
      cur = { colour, points: cur ? [cur.points[cur.points.length - 1]] : [] }
      out.push(cur)
    }
    cur.points.push(pts[i])
  }
  return out
}

export const fmtPace = (s) => (s && Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}/km` : '')
