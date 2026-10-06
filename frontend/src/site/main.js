import { mount } from 'svelte'
import 'leaflet/dist/leaflet.css'
import '../app.css'
import './site.css'
import Site from './Site.svelte'

// The published HTML carries a plain-text version of each page for search
// engines; the app replaces it.
const target = document.getElementById('app')
target.replaceChildren()
export default mount(Site, { target })
