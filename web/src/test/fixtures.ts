// The backend's saved API responses, for tests. Fixture names follow the
// fixture server: `get_targets.json`, `post_decide.partial.json`.
const FIXTURE_DIR = '../../../tests/fixtures/api/'

const files = import.meta.glob<unknown>('../../../tests/fixtures/api/*.json', {
  eager: true,
  import: 'default',
})

export function fixture<T>(name: string): T {
  const value = files[`${FIXTURE_DIR}${name}`]
  if (value === undefined) throw new Error(`No fixture named ${name}`)
  return structuredClone(value) as T
}
