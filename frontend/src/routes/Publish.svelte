<script>
  // Public site: what's on it, preview, publish to GitHub Pages, settings.
  import { onMount, onDestroy } from 'svelte'
  import { api } from '../lib/api.js'
  import { notify } from '../lib/stores.svelte.js'
  import { fmtBytes, PUBLISH_LEVELS } from '../lib/format.js'

  let settings = $state(null)
  let saved = $state('')
  let info = $state({ token: false, site_url: null, repo: null })
  let gh = $state(null)
  let checking = $state(false)
  let preview = $state(null)
  let building = $state(false)
  let runs = $state([])
  let busy = $state(false)
  let poll

  const running = $derived(runs.find((r) => r.status === 'running'))
  const last = $derived(runs.find((r) => r.status !== 'running'))
  const dirty = $derived(settings && JSON.stringify(settings) !== saved)

  async function load() {
    const res = await api.get('/api/publish/settings')
    settings = pick(res.settings)
    saved = JSON.stringify(settings)
    info = res
  }
  const FIELDS = ['site_title', 'site_description', 'author', 'contact', 'about', 'github_repo', 'github_branch', 'site_url']
  const pick = (s) => Object.fromEntries(FIELDS.map((k) => [k, s[k] ?? '']))

  async function loadRuns() {
    runs = await api.get('/api/publish/runs')
    clearTimeout(poll)
    if (runs.some((r) => r.status === 'running')) poll = setTimeout(loadRuns, 1500)
  }

  async function check() {
    checking = true
    try { gh = await api.get('/api/publish/github'); await load() } catch (e) { notify(e.message, 'error') }
    checking = false
  }

  async function save() {
    busy = true
    try { await api.put('/api/publish/settings', settings); await load(); notify('Settings saved') } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  async function buildPreview() {
    building = true
    try { preview = await api.post('/api/publish/preview') } catch (e) { notify(e.message, 'error') }
    building = false
  }

  async function publishNow() {
    if (dirty && !confirm('You have unsaved settings. Publish without them?')) return
    busy = true
    try { await api.post('/api/publish'); await loadRuns() } catch (e) { notify(e.message, 'error') }
    busy = false
  }

  onMount(async () => {
    try { await Promise.all([load(), loadRuns()]) } catch (e) { notify(e.message, 'error') }
    if (info.token) check()
    buildPreview()
  })
  onDestroy(() => clearTimeout(poll))

  const when = (d) => d ? new Date(d).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
  const levelLabel = (v) => PUBLISH_LEVELS.find((l) => l.value === v)?.label ?? v
  const ready = $derived(info.token && gh && !gh.error && gh.repo_exists)
</script>

<main class="page">
  <div class="row head">
    <h1>Public site</h1>
    <span class="spacer"></span>
    <a class="btn" href="/site-preview/" target="_blank" rel="noopener">Open preview ↗</a>
    <button class="primary" onclick={publishNow} disabled={busy || !!running || !ready} title={ready ? '' : 'Connect GitHub first (below)'}>
      {running ? 'Publishing…' : 'Publish now'}
    </button>
  </div>

  <div class="grid">
    <section class="card">
      <h2>What goes out</h2>
      {#if !preview}
        <p class="muted">{building ? 'Building the preview…' : 'No preview yet.'}</p>
      {:else}
        <p>
          <strong>{preview.maps}</strong> map{preview.maps === 1 ? '' : 's'}:
          {#each PUBLISH_LEVELS.slice(1) as l, i}{i ? ', ' : ''}{preview.counts[l.value] ?? 0} {l.label.toLowerCase()}{/each}.
          {preview.files} files, {fmtBytes(preview.size)}.
        </p>
        {#if preview.pending}
          {@const p = preview.pending}
          <p class:muted={!p.added && !p.changed && !p.removed}>
            Since the last publish: {p.added} new, {p.changed} changed, {p.removed} removed{p.bytes ? ` (${fmtBytes(p.bytes)} to upload)` : ''}.
          </p>
        {:else}
          <p class="muted">Not published yet: everything is new.</p>
        {/if}
        {#if !preview.maps}
          <p class="hint">Choose which maps go on the site with the “Public site” setting on each map page, or filter the library on it.</p>
        {/if}
        {#if preview.warnings.length}
          <details>
            <summary>{preview.warnings.length} map{preview.warnings.length === 1 ? '' : 's'} to check</summary>
            <ul class="warn">
              {#each preview.warnings as w}
                <li><a href="#/map/{w.map_id}">{w.name}</a> <span class="chip">{levelLabel(w.level)}</span> {w.issues.join('; ')}</li>
              {/each}
            </ul>
          </details>
        {/if}
      {/if}
      <div class="row">
        <button onclick={buildPreview} disabled={building}>{building ? 'Building…' : 'Refresh preview'}</button>
        <a href="#/" class="small">Library</a>
      </div>
    </section>

    <section class="card">
      <h2>GitHub</h2>
      {#if !info.token}
        <p>No GitHub token yet. To connect:</p>
        <ol class="steps">
          <li>On GitHub, create a <strong>public</strong>, empty repository named <code>{settings?.github_repo || 'orienteeringmaps-public'}</code>.</li>
          <li>Create a <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">fine-grained token</a>: only that repository, with <em>Contents</em> and <em>Pages</em> set to “Read and write”.</li>
          <li>Put it in <code>.env</code> next to <code>docker-compose.yml</code> as <code>OMAPS_GITHUB_TOKEN=…</code> and restart the container.</li>
        </ol>
      {:else if !gh}
        <p class="muted">{checking ? 'Checking GitHub…' : 'Not checked yet.'}</p>
      {:else}
        {#if gh.error}<p class="err">{gh.error}</p>{/if}
        <dl class="facts">
          {#if gh.login}<div><dt>Account</dt><dd>{gh.login}</dd></div>{/if}
          {#if gh.repo}<div><dt>Repository</dt><dd>{#if gh.html_url}<a href={gh.html_url} target="_blank" rel="noopener">{gh.repo}</a>{:else}{gh.repo}{/if}</dd></div>{/if}
          {#if gh.repo_exists}<div><dt>Pages</dt><dd>{gh.pages ? gh.pages.status ?? 'on' : 'switched on at first publish'}</dd></div>{/if}
          {#if gh.private}<div><dt>Warning</dt><dd class="err">Repository is private</dd></div>{/if}
        </dl>
      {/if}
      {#if info.site_url}
        <p>Address: <a href={info.site_url} target="_blank" rel="noopener">{info.site_url}</a></p>
      {/if}
      {#if info.token}<button onclick={check} disabled={checking}>{checking ? 'Checking…' : 'Check again'}</button>{/if}
    </section>
  </div>

  {#if runs.length}
    <section class="card">
      <h2>Publish history</h2>
      <ul class="runs">
        {#each runs as r (r.id)}
          <li>
            <details open={r.status === 'running' || (r === last && r.status === 'error')}>
              <summary>
                <span class="chip {r.status === 'error' ? 'warn' : r.status === 'running' ? 'accent' : 'ok'}">{r.status}</span>
                {when(r.started_at)}
                {#if r.summary}<span class="muted">· {r.summary.maps} maps · {r.summary.added} new, {r.summary.changed} changed, {r.summary.removed} removed</span>{/if}
                {#if r.commit_sha && r.repo}<a href="https://github.com/{r.repo}/commit/{r.commit_sha}" target="_blank" rel="noopener">{r.commit_sha.slice(0, 7)}</a>{/if}
              </summary>
              <pre>{r.log}</pre>
            </details>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if settings}
    <section class="card">
      <h2>Settings</h2>
      <div class="grid-form">
        <label class="field"><span>Site title</span><input bind:value={settings.site_title} /></label>
        <label class="field wide"><span>Short description</span><input bind:value={settings.site_description} /></label>
        <label class="field"><span>Your name <span class="hint">(optional, on the About page)</span></span><input bind:value={settings.author} /></label>
        <label class="field"><span>Contact for removal requests <span class="hint">(email or URL, public)</span></span><input bind:value={settings.contact} /></label>
        <label class="field wide"><span>About text <span class="hint">(blank line = new paragraph)</span></span><textarea bind:value={settings.about} rows="4"></textarea></label>
        <label class="field"><span>GitHub repository <span class="hint">(name, or owner/name)</span></span><input bind:value={settings.github_repo} placeholder="orienteeringmaps-public" /></label>
        <label class="field"><span>Branch</span><input bind:value={settings.github_branch} placeholder="main" /></label>
        <label class="field wide"><span>Site address <span class="hint">(leave empty for https://&lt;account&gt;.github.io/&lt;repository&gt;/; set it for a custom domain)</span></span><input bind:value={settings.site_url} placeholder={info.site_url ?? 'https://…'} /></label>
      </div>
      <div class="row end">
        <span class="hint">Changes reach the public site at the next publish.</span>
        <span class="spacer"></span>
        <button class="primary" onclick={save} disabled={!dirty || busy}>Save settings</button>
      </div>
    </section>
  {/if}
</main>

<style>
  .head { margin-bottom: 1rem; }
  .head h1 { margin: 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
  section.card { margin-bottom: 1rem; }
  .grid section.card { margin-bottom: 0; }
  .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: .5rem 1rem; margin: 0 0 .75rem; }
  .facts dt { font-size: .78rem; color: var(--muted); }
  .facts dd { margin: 0; font-weight: 500; overflow-wrap: anywhere; }
  .steps { padding-left: 1.2rem; }
  .steps li { margin-bottom: .4rem; }
  .err { color: var(--danger); }
  .warn { padding-left: 1.1rem; font-size: .9rem; }
  .warn li { margin: .25rem 0; }
  .runs { list-style: none; padding: 0; margin: 0; }
  .runs li { border-top: 1px solid var(--border); padding: .45rem 0; }
  .runs li:first-child { border-top: 0; }
  summary { cursor: pointer; display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
  pre { white-space: pre-wrap; font-family: var(--mono); font-size: .8rem; background: var(--surface-2); padding: .6rem; border-radius: 6px; margin: .5rem 0 0; }
  .end { margin-top: 1rem; }
  .small { font-size: .85rem; }
  code { font-family: var(--mono); font-size: .88em; }
</style>
