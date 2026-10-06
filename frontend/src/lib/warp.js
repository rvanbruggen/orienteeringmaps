// Projective image warping for Leaflet.
//
// A page image is placed by its four corners (TL, TR, BR, BL as lat/lon).
// For the current zoom we map the image's pixel corners to layer points and
// apply the resulting homography as a CSS matrix3d. That reproduces any
// similarity, affine or projective fit exactly, because Web Mercator ->
// layer pixels is itself a scale + shift at a given zoom.
import L from 'leaflet'

/** Solve A x = b (n x n) by Gaussian elimination with partial pivoting. */
function solve(A, b) {
  const n = b.length
  const M = A.map((row, i) => [...row, b[i]])
  for (let c = 0; c < n; c++) {
    let p = c
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r
    ;[M[c], M[p]] = [M[p], M[c]]
    for (let r = c + 1; r < n; r++) {
      const f = M[r][c] / M[c][c]
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]
    }
  }
  const x = new Array(n)
  for (let r = n - 1; r >= 0; r--) {
    let s = M[r][n]
    for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]
    x[r] = s / M[r][r]
  }
  return x
}

/** 3x3 homography (row-major, h22 = 1) mapping 4 src points onto 4 dst points. */
export function homography(src, dst) {
  const A = [], b = []
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i]
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u)
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v)
  }
  const h = solve(A, b)
  return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]]
}

export function applyH(H, x, y) {
  const w = H[2][0] * x + H[2][1] * y + H[2][2]
  return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w]
}

export function invert3(m) {
  const [[a, b, c], [d, e, f], [g, h, i]] = m
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g
  const det = a * A + b * B + c * C
  return [
    [A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det],
  ]
}

const R = 6378137
export const toMerc = (lat, lon) => [R * lon * Math.PI / 180, R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))]
export const fromMerc = (x, y) => [(2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI, x / R * 180 / Math.PI]

/** Image pixel -> [lat, lon] with a fitted matrix (image px -> Mercator). */
export const pixelToLatLon = (H, x, y) => fromMerc(...applyH(H, x, y))
/** [lat, lon] -> image pixel with the inverse of a fitted matrix. */
export const latLonToPixel = (Hinv, lat, lon) => applyH(Hinv, ...toMerc(lat, lon))

/** Map image pixel polygons to [lat, lon] using the four placed corners. */
export function pixelsToLatLons(width, height, corners, pixels) {
  const H = homography([[0, 0], [width, 0], [width, height], [0, height]], corners.map(([lat, lon]) => toMerc(lat, lon)))
  return pixels.map(([x, y]) => fromMerc(...applyH(H, x, y)))
}

export const WarpedImage = L.Layer.extend({
  options: { opacity: 0.75, clip: null, pane: 'overlayPane', className: '' },

  initialize(url, width, height, corners, options) {
    this._url = url
    this._w = width
    this._h = height
    this._corners = corners
    L.setOptions(this, options)
  },

  onAdd(map) {
    const img = (this._img = L.DomUtil.create('img', `leaflet-zoom-hide omaps-warped ${this.options.className}`))
    img.src = this._url
    img.alt = ''
    Object.assign(img.style, {
      position: 'absolute', left: '0', top: '0', width: `${this._w}px`, height: `${this._h}px`,
      maxWidth: 'none', transformOrigin: '0 0', pointerEvents: 'none', userSelect: 'none',
    })
    this.getPane().appendChild(img)
    this._applyStyle()
    map.on('zoomend viewreset resize', this._update, this)
    this._update()
  },

  onRemove(map) {
    map.off('zoomend viewreset resize', this._update, this)
    this._img?.remove()
    this._img = null
  },

  setCorners(corners) { this._corners = corners; this._update(); return this },
  setOpacity(o) { this.options.opacity = o; this._applyStyle(); return this },
  setClip(clip) { this.options.clip = clip; this._applyStyle(); return this },
  getBounds() { return L.latLngBounds(this._corners) },

  _applyStyle() {
    if (!this._img) return
    this._img.style.opacity = this.options.opacity
    const c = this.options.clip
    this._img.style.clipPath = c?.length >= 3 ? `polygon(${c.map(([x, y]) => `${x}px ${y}px`).join(',')})` : ''
  },

  _update() {
    if (!this._map || !this._img || !this._corners) return
    const dst = this._corners.map((c) => {
      const p = this._map.latLngToLayerPoint(c)
      return [p.x, p.y]
    })
    const H = homography([[0, 0], [this._w, 0], [this._w, this._h], [0, this._h]], dst)
    // CSS matrix3d is column-major.
    const m = [H[0][0], H[1][0], 0, H[2][0], H[0][1], H[1][1], 0, H[2][1], 0, 0, 1, 0, H[0][2], H[1][2], 0, H[2][2]]
    this._img.style.transform = `matrix3d(${m.join(',')})`
  },
})
