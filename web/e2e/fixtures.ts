import { readFileSync } from 'node:fs'

/** A saved API response from tests/fixtures/api/, for checking what a view shows. */
export function fixture<T>(name: string): T {
  const url = new URL(`../../tests/fixtures/api/${name}`, import.meta.url)
  return JSON.parse(readFileSync(url, 'utf8')) as T
}
