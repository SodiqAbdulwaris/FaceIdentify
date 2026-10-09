// The bridge to the desktop shell: where the backend is and what only the shell can do.
//
// The shell starts the backend and owns the per-launch token; the web view asks it (never the
// network) for the connection. In a plain browser (`npm run dev`) there is no shell, so a backend
// started by hand can be named with VITE_BACKEND_URL and VITE_BACKEND_TOKEN for development.

import { invoke } from '@tauri-apps/api/core'

export interface Connection {
  base_url: string
  events_url: string
  token: string
  protocol: string
}

export type BackendStatus =
  | { state: 'starting' }
  | { state: 'ready'; connection: Connection }
  | { state: 'failed'; error: string }

export const NO_SHELL_MESSAGE =
  'FaceIdentify has to be opened through the desktop app. For browser development, set ' +
  'VITE_BACKEND_URL and VITE_BACKEND_TOKEN to a backend started by hand.'

export function inShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function backendStatus(): Promise<BackendStatus> {
  if (inShell()) return invoke<BackendStatus>('backend_status')
  const base = import.meta.env.VITE_BACKEND_URL as string | undefined
  const token = import.meta.env.VITE_BACKEND_TOKEN as string | undefined
  if (!base || !token) return { state: 'failed', error: NO_SHELL_MESSAGE }
  return {
    state: 'ready',
    connection: {
      base_url: base,
      events_url: `${base.replace(/^http/, 'ws')}/api/v1/events`,
      token,
      protocol: 'faceidentify.v1',
    },
  }
}

/** The image files the user picks in the native dialog (empty if they cancel or there is no shell). */
export async function chooseImages(): Promise<string[]> {
  return inShell() ? invoke<string[]>('choose_images') : []
}

/** The one picture the user picks in the native dialog to search with (null if they cancel). */
export async function choosePicture(): Promise<string | null> {
  return inShell() ? invoke<string | null>('choose_picture') : null
}

/** Where the library is kept (empty outside the shell). */
export async function libraryRoot(): Promise<string> {
  if (!inShell()) return ''
  const info = await invoke<{ library_root: string }>('library_info')
  return info.library_root
}
