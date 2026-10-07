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

// ---------------------------------------------------------------- geometry --

const EARTH = 6371000
const RAD = Math.PI / 180

/** A local flat frame around (lat0, lon0) in metres: x east, y north. Fine for a few km. */
export function localFrame(lat0, lon0) {
  const k = Math.cos(lat0 * RAD)
  return {
    toXY: (lat, lon) => [(lon - lon0) * RAD * EARTH * k, (lat - lat0) * RAD * EARTH],
    toLatLon: (x, y) => [lat0 + y / EARTH / RAD, lon0 + x / (EARTH * k) / RAD],
  }
}

export function distM([lat1, lon1], [lat2, lon2]) {
  const k = Math.cos(((lat1 + lat2) / 2) * RAD)
  return EARTH * RAD * Math.hypot(lat2 - lat1, (lon2 - lon1) * k)
}

/**
 * The route with a GPS correction applied: rotated `rot` degrees clockwise around its middle,
 * then shifted dx metres east and dy metres north. Returns the same object when there is nothing to do.
 */
export function adjustRoute(route, adj) {
  if (!adj || (!adj.dx && !adj.dy && !adj.rot) || !route.latlng.length) return route
  const lats = route.latlng.map((p) => p[0]), lons = route.latlng.map((p) => p[1])
  const c = [(Math.min(...lats) + Math.max(...lats)) / 2, (Math.min(...lons) + Math.max(...lons)) / 2]
  const f = localFrame(...c)
  const th = (adj.rot || 0) * RAD, cos = Math.cos(th), sin = Math.sin(th)
  const latlng = route.latlng.map(([lat, lon]) => {
    const [x, y] = f.toXY(lat, lon)
    return f.toLatLon(x * cos + y * sin + (adj.dx || 0), -x * sin + y * cos + (adj.dy || 0))
  })
  return { ...route, latlng }
}

/** Where you were at time t (seconds from the start): {latlng, i} with i the last point at or before t. */
export function positionAt(route, t) {
  const { time, latlng } = route
  if (!time?.length) return null
  if (t <= time[0]) return { latlng: latlng[0], i: 0 }
  const n = time.length
  if (t >= time[n - 1]) return { latlng: latlng[n - 1], i: n - 1 }
  let lo = 0, hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (time[mid] <= t) lo = mid
    else hi = mid
  }
  const f = (t - time[lo]) / (time[hi] - time[lo] || 1)
  const [a, b] = [latlng[lo], latlng[hi]]
  return { latlng: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f], i: lo }
}

// ------------------------------------------------------------------ splits --

export const CONTROL_RADIUS_M = 30 // you "visited" a control when the route came this close

/**
 * Find when the route passed each control, in order (first is the start, last the finish), and split
 * the run into legs. A control counts as visited at the closest point of the first pass within
 * CONTROL_RADIUS_M after the previous control; if the route never comes that close, the closest point
 * after the previous control is used and the leg is marked uncertain.
 */
export function legSplits(route, controls) {
  const { latlng, time, distance } = route
  if (!controls || controls.length < 2 || !latlng.length || !time?.length) return null
  const n = latlng.length
  const visits = []
  let from = 0
  for (const c of controls) {
    let best = -1, bestD = Infinity, inside = false, fallback = from, fallbackD = Infinity
    for (let j = from; j < n; j++) {
      const d = distM(latlng[j], c)
      if (d < fallbackD) { fallbackD = d; fallback = j }
      if (d <= CONTROL_RADIUS_M) {
        inside = true
        if (d < bestD) { bestD = d; best = j }
      } else if (inside) break // left the circle: this was the first pass
    }
    const i = best >= 0 ? best : fallback
    visits.push({ i, missDistance: best >= 0 ? 0 : Math.round(fallbackD), uncertain: best < 0 })
    from = i
  }
  const legs = []
  for (let k = 1; k < controls.length; k++) {
    const a = visits[k - 1], b = visits[k]
    const t = time[b.i] - time[a.i]
    const run = distance?.length ? distance[b.i] - distance[a.i] : null
    const straight = distM(controls[k - 1], controls[k])
    legs.push({
      k, from: a.i, to: b.i, time: t, total: time[b.i] - time[visits[0].i],
      run, straight, extra: run != null && straight > 0 ? run / straight - 1 : null,
      pace: run > 0 ? (t / run) * 1000 : null, uncertain: b.uncertain || (k === 1 && a.uncertain),
      missDistance: b.missDistance,
    })
  }
  return { visits, legs }
}
