#!/usr/bin/env node
// Idempotently bootstrap a test workspace in an Inspector Supabase project.
//
// Creates (or finds, if already present):
//   1. auth.users row for $TEST_USER_EMAIL with $TEST_USER_PASSWORD (email_confirm=true)
//   2. workspaces row "Mason E2E test"
//   3. workspace_members row owner-role
//   4. integration_configs(integration_name='posthog') connected, with the
//      Project B API key encrypted via Inspector's AES-256-GCM scheme.
//   5. posthog_workspace_config row pointing at Project B (project_id, host).
//   6. integration_configs(integration_name='attio') connected stub so
//      computeSetupStatus() returns setupComplete=true without a real Attio.
//
// Standalone — no npm install required, only Node.js stdlib + Supabase REST.
//
// Required env (read from `~/.claude/secrets/mason-flash3.env` + Inspector .env):
//   SUPABASE_URL                Supabase project URL (Inspector test project / branch)
//   SUPABASE_SERVICE_ROLE_KEY   Service-role JWT for that project
//   ENCRYPTION_KEY              64-char hex; MUST match the local Inspector dev
//                               server's ENCRYPTION_KEY so encrypted columns decrypt.
//   POSTHOG_PERSONAL_API_KEY    phx_… read-scope key (used by Inspector to query)
//   POSTHOG_PROJECT_ID          numeric project id (e.g. 406509)
//   POSTHOG_HOST                https://us.posthog.com
//
// Optional env:
//   TEST_USER_EMAIL             default vlad@getbeton.info
//   TEST_USER_PASSWORD          default Mason-E2E-2026!
//   WORKSPACE_NAME              default "Mason E2E test"
//   WORKSPACE_SLUG              default mason-e2e-test
//   WEBSITE_URL                 default https://mason-test.example.com
//
// Output: prints workspace_id, user_id, and the test_user_password to stdout
// as a JSON envelope. Pipe it into the run.sh harness if you wish.

import { createCipheriv, randomBytes, scrypt } from 'node:crypto'
import { promisify } from 'node:util'

const scryptAsync = promisify(scrypt)

// ── Env ─────────────────────────────────────────────────────────────
const must = (name) => {
  const v = process.env[name]
  if (!v) {
    console.error(`ERROR: ${name} env var is required.`)
    process.exit(2)
  }
  return v
}
const SUPABASE_URL = must('SUPABASE_URL').replace(/\/+$/, '')
const SERVICE_ROLE_KEY = must('SUPABASE_SERVICE_ROLE_KEY')
const ENCRYPTION_KEY = must('ENCRYPTION_KEY')
const PH_PERSONAL_KEY = must('POSTHOG_PERSONAL_API_KEY')
const PH_PROJECT_ID = must('POSTHOG_PROJECT_ID')
const PH_HOST = (process.env.POSTHOG_HOST || 'https://us.posthog.com').replace(/\/+$/, '')

const TEST_EMAIL = process.env.TEST_USER_EMAIL || 'vlad@getbeton.info'
const TEST_PASSWORD = process.env.TEST_USER_PASSWORD || 'Mason-E2E-2026!'
const WORKSPACE_NAME = process.env.WORKSPACE_NAME || 'Mason E2E test'
const WORKSPACE_SLUG = process.env.WORKSPACE_SLUG || 'mason-e2e-test'
const WEBSITE_URL = process.env.WEBSITE_URL || 'https://mason-test.example.com'

const REST_HEADERS = {
  apikey: SERVICE_ROLE_KEY,
  Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
  'Content-Type': 'application/json',
  Prefer: 'return=representation',
}

// ── HTTP helper ────────────────────────────────────────────────────
async function api(method, path, body) {
  const url = `${SUPABASE_URL}${path}`
  const init = { method, headers: REST_HEADERS }
  if (body !== undefined) init.body = JSON.stringify(body)
  const res = await fetch(url, init)
  const text = await res.text()
  let parsed = null
  try { parsed = text ? JSON.parse(text) : null } catch { parsed = text }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} ${method} ${path}`)
    err.status = res.status
    err.body = parsed
    throw err
  }
  return parsed
}

// ── AES-256-GCM encrypt (matches Inspector's encrypt() output) ─────
async function encrypt(plaintext) {
  const salt = randomBytes(16)
  const iv = randomBytes(12)
  const key = await scryptAsync(ENCRYPTION_KEY, salt, 32)
  const cipher = createCipheriv('aes-256-gcm', key, iv, { authTagLength: 16 })
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return [salt.toString('hex'), iv.toString('hex'), tag.toString('hex'), encrypted.toString('hex')].join(':')
}

// ── Auth admin: idempotent createUser ──────────────────────────────
async function ensureAuthUser() {
  // List users (paginated). The auth admin API uses PostgREST-incompatible
  // paths under /auth/v1/admin/.
  const listUrl = `${SUPABASE_URL}/auth/v1/admin/users?per_page=200`
  const listRes = await fetch(listUrl, {
    headers: { apikey: SERVICE_ROLE_KEY, Authorization: `Bearer ${SERVICE_ROLE_KEY}` },
  })
  if (!listRes.ok) throw new Error(`auth admin users list failed: ${listRes.status} ${await listRes.text()}`)
  const listJson = await listRes.json()
  const existing = (listJson.users || []).find((u) => u.email === TEST_EMAIL)
  if (existing) {
    console.error(`>> auth user exists: ${existing.id}`)
    return existing
  }
  const createRes = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
    method: 'POST',
    headers: { apikey: SERVICE_ROLE_KEY, Authorization: `Bearer ${SERVICE_ROLE_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
      email_confirm: true,
      user_metadata: { full_name: 'Mason E2E' },
    }),
  })
  if (!createRes.ok) throw new Error(`auth admin createUser failed: ${createRes.status} ${await createRes.text()}`)
  const created = await createRes.json()
  console.error(`>> created auth user: ${created.id}`)
  return created
}

// ── Workspace + membership ─────────────────────────────────────────
async function ensureWorkspaceAndMember(userId) {
  // Look up existing membership first.
  const memberRows = await api('GET', `/rest/v1/workspace_members?user_id=eq.${userId}&select=workspace_id,role`)
  if (Array.isArray(memberRows) && memberRows.length) {
    const wsId = memberRows[0].workspace_id
    console.error(`>> existing workspace_member found: workspace_id=${wsId}`)
    return wsId
  }
  // Create workspace.
  const slug = `${WORKSPACE_SLUG}-${Date.now()}`
  const created = await api('POST', '/rest/v1/workspaces', [{
    name: WORKSPACE_NAME,
    slug,
    website_url: WEBSITE_URL,
  }])
  const wsId = created[0].id
  console.error(`>> created workspace: ${wsId} (slug=${slug})`)
  await api('POST', '/rest/v1/workspace_members', [{
    workspace_id: wsId,
    user_id: userId,
    role: 'owner',
  }])
  console.error('>> created workspace_members owner row')
  return wsId
}

// ── PostHog config ─────────────────────────────────────────────────
async function ensurePostHogConfig(workspaceId) {
  const existing = await api(
    'GET',
    `/rest/v1/integration_configs?workspace_id=eq.${workspaceId}&integration_name=eq.posthog&select=id`,
  )
  const apiKeyEncrypted = await encrypt(PH_PERSONAL_KEY)
  const configJson = {
    project_id: PH_PROJECT_ID,
    host: PH_HOST,
  }
  if (Array.isArray(existing) && existing.length) {
    const id = existing[0].id
    await api('PATCH', `/rest/v1/integration_configs?id=eq.${id}`, {
      api_key_encrypted: apiKeyEncrypted,
      config_json: configJson,
      status: 'connected',
      is_active: true,
      last_validated_at: new Date().toISOString(),
    })
    console.error(`>> updated integration_configs(posthog) ${id}`)
  } else {
    await api('POST', '/rest/v1/integration_configs', [{
      workspace_id: workspaceId,
      integration_name: 'posthog',
      api_key_encrypted: apiKeyEncrypted,
      config_json: configJson,
      status: 'connected',
      is_active: true,
      last_validated_at: new Date().toISOString(),
    }])
    console.error('>> created integration_configs(posthog)')
  }

  // posthog_workspace_config (separate table, indexed by workspace).
  const phRows = await api(
    'GET',
    `/rest/v1/posthog_workspace_config?workspace_id=eq.${workspaceId}&select=id`,
  )
  const phPayload = {
    workspace_id: workspaceId,
    posthog_api_key: apiKeyEncrypted,
    posthog_project_id: PH_PROJECT_ID,
    is_validated: true,
    validated_at: new Date().toISOString(),
    is_active: true,
  }
  if (Array.isArray(phRows) && phRows.length) {
    await api('PATCH', `/rest/v1/posthog_workspace_config?id=eq.${phRows[0].id}`, phPayload)
    console.error('>> updated posthog_workspace_config')
  } else {
    await api('POST', '/rest/v1/posthog_workspace_config', [phPayload])
    console.error('>> created posthog_workspace_config')
  }
}

// ── Attio stub (so computeSetupStatus passes) ──────────────────────
async function ensureAttioStub(workspaceId) {
  const existing = await api(
    'GET',
    `/rest/v1/integration_configs?workspace_id=eq.${workspaceId}&integration_name=eq.attio&select=id`,
  )
  const stubKey = await encrypt('attio-stub-key-for-mason-e2e')
  if (Array.isArray(existing) && existing.length) {
    await api('PATCH', `/rest/v1/integration_configs?id=eq.${existing[0].id}`, {
      api_key_encrypted: stubKey,
      status: 'connected',
      is_active: true,
    })
    console.error('>> updated integration_configs(attio) stub')
  } else {
    await api('POST', '/rest/v1/integration_configs', [{
      workspace_id: workspaceId,
      integration_name: 'attio',
      api_key_encrypted: stubKey,
      config_json: { stub: true, mason_e2e: true },
      status: 'connected',
      is_active: true,
    }])
    console.error('>> created integration_configs(attio) stub')
  }
}

// ── Main ───────────────────────────────────────────────────────────
async function main() {
  const user = await ensureAuthUser()
  const workspaceId = await ensureWorkspaceAndMember(user.id)
  await ensurePostHogConfig(workspaceId)
  await ensureAttioStub(workspaceId)
  const out = {
    user_id: user.id,
    user_email: TEST_EMAIL,
    user_password: TEST_PASSWORD,
    workspace_id: workspaceId,
    workspace_name: WORKSPACE_NAME,
    posthog_project_id: PH_PROJECT_ID,
    posthog_host: PH_HOST,
  }
  console.log(JSON.stringify(out, null, 2))
}

main().catch((err) => {
  console.error('FAILED:', err.message)
  if (err.body) console.error('  body:', typeof err.body === 'string' ? err.body : JSON.stringify(err.body, null, 2))
  process.exit(1)
})
