/**
 * Storage compatibility utility for CocoCV rebranding and legacy downward migration.
 * Issue #53 & Milestone 2.
 *
 * Implements smooth downward compatibility:
 * - Checks modern key (e.g., cococv_*) first.
 * - Falls back to legacy keys (e.g., resume_*, resume-agent-*) in specified order.
 * - Migrates discovered legacy values forward to the modern key automatically.
 */

export const DEFAULT_KEY_MAP: Record<string, string[]> = {
  cococv_resumes: ['resume_resumes', 'resume-agent-resumes'],
  cococv_current: ['resume_current', 'resume-agent-current'],
  cococv_v2_data: ['resume_v2_data', 'resume-agent-v2-data'],
  cococv_pinned_ids: ['resume_pinned_ids', 'resume-agent-pinned-ids'],
};

function getStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Get an item from localStorage with downward compatibility fallback and automatic forward migration.
 *
 * @param newKey Primary modern key (e.g. cococv_*)
 * @param legacyKeys Ordered list of legacy keys to probe if newKey is missing
 * @returns The stored string value or null if not found
 */
export function getCompatibleItem(
  newKey: string,
  legacyKeys: string[] = []
): string | null {
  const storage = getStorage();
  if (!storage) return null;

  try {
    // 1. Probe primary modern key
    const modernVal = storage.getItem(newKey);
    if (modernVal !== null) {
      return modernVal;
    }

    // 2. Resolve fallback legacy keys
    const probeKeys =
      legacyKeys.length > 0
        ? legacyKeys
        : DEFAULT_KEY_MAP[newKey] || [];

    // 3. Probe legacy keys in priority order
    for (const legKey of probeKeys) {
      const legVal = storage.getItem(legKey);
      if (legVal !== null) {
        // 4. Asynchronously / immediately forward-migrate to newKey
        try {
          storage.setItem(newKey, legVal);
        } catch {
          // Ignore quota/write errors, still return the retrieved value
        }
        return legVal;
      }
    }
  } catch (err) {
    console.warn(`[storageCompat] Read error for key ${newKey}:`, err);
  }

  return null;
}

/**
 * Set an item in localStorage under the modern key, optionally syncing legacy keys.
 *
 * @param newKey Primary modern key
 * @param value String value to store
 * @param legacyKeys Optional legacy keys to update for dual compatibility
 */
export function setCompatibleItem(
  newKey: string,
  value: string,
  legacyKeys?: string[]
): void {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.setItem(newKey, value);
    if (legacyKeys && legacyKeys.length > 0) {
      for (const legKey of legacyKeys) {
        try {
          storage.setItem(legKey, value);
        } catch {
          // Ignore secondary write errors
        }
      }
    }
  } catch (err) {
    console.warn(`[storageCompat] Write error for key ${newKey}:`, err);
  }
}

/**
 * Remove an item from localStorage, purging both the modern key and associated legacy keys.
 *
 * @param newKey Primary modern key
 * @param legacyKeys Optional legacy keys to purge
 */
export function removeCompatibleItem(
  newKey: string,
  legacyKeys?: string[]
): void {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.removeItem(newKey);
    const keysToRemove = legacyKeys || DEFAULT_KEY_MAP[newKey] || [];
    for (const legKey of keysToRemove) {
      try {
        storage.removeItem(legKey);
      } catch {
        // Ignore
      }
    }
  } catch (err) {
    console.warn(`[storageCompat] Remove error for key ${newKey}:`, err);
  }
}

/**
 * Perform a full forward-migration of all registered legacy keys in DEFAULT_KEY_MAP.
 */
export function migrateAllRegisteredKeys(): void {
  for (const [newKey, legacyKeys] of Object.entries(DEFAULT_KEY_MAP)) {
    getCompatibleItem(newKey, legacyKeys);
  }
}
