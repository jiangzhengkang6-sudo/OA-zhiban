import type { RoomKit } from '@tencentcloud/roomkit-web-vue3'

// RoomKit is a singleton across component mounts, so teardown must be shared too.
let cleanup: Promise<void> = Promise.resolve()

export function pendingVideoCleanup() { return cleanup }

export function destroyVideoRoom(library: { RoomKit: typeof RoomKit }) {
  cleanup = cleanup.catch(() => {}).then(() => library.RoomKit.destroyInstance())
  return cleanup
}
