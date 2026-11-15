// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getCompatibleItem,
  setCompatibleItem,
  removeCompatibleItem,
  migrateAllRegisteredKeys,
  DEFAULT_KEY_MAP,
} from './storageCompat';

describe('storageCompat', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('getCompatibleItem', () => {
    it('returns modern cococv_* item directly when present without inspecting legacy', () => {
      localStorage.setItem('cococv_current', 'res_modern_123');
      localStorage.setItem('resume_current', 'res_legacy_999');

      const result = getCompatibleItem('cococv_current', ['resume_current']);
      expect(result).toBe('res_modern_123');
      expect(localStorage.getItem('cococv_current')).toBe('res_modern_123');
    });

    it('falls back to legacy key when modern key is missing and migrates forward', () => {
      localStorage.setItem('resume_current', 'res_legacy_456');

      expect(localStorage.getItem('cococv_current')).toBeNull();

      const result = getCompatibleItem('cococv_current', [
        'resume_current',
        'resume-agent-current',
      ]);

      expect(result).toBe('res_legacy_456');
      // Verify forward migration
      expect(localStorage.getItem('cococv_current')).toBe('res_legacy_456');
    });

    it('respects legacy priority order when multiple legacy keys exist', () => {
      localStorage.setItem('resume_primary', 'first_priority');
      localStorage.setItem('resume_secondary', 'second_priority');

      const result = getCompatibleItem('cococv_test', [
        'resume_primary',
        'resume_secondary',
      ]);

      expect(result).toBe('first_priority');
      expect(localStorage.getItem('cococv_test')).toBe('first_priority');
    });

    it('uses DEFAULT_KEY_MAP when legacyKeys array is omitted', () => {
      localStorage.setItem('resume_v2_data', JSON.stringify({ title: '默认映射简历' }));

      expect(localStorage.getItem('cococv_v2_data')).toBeNull();

      const result = getCompatibleItem('cococv_v2_data');
      expect(result).toBe(JSON.stringify({ title: '默认映射简历' }));
      expect(localStorage.getItem('cococv_v2_data')).toBe(
        JSON.stringify({ title: '默认映射简历' })
      );
    });

    it('returns null when neither modern nor legacy keys exist', () => {
      const result = getCompatibleItem('cococv_nonexistent', ['resume_nonexistent']);
      expect(result).toBeNull();
    });

    it('handles localStorage throwing errors gracefully', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => {
        throw new Error('SecurityError: Access denied');
      });

      const result = getCompatibleItem('cococv_test', ['resume_test']);
      expect(result).toBeNull();
    });
  });

  describe('setCompatibleItem', () => {
    it('sets the modern key in localStorage', () => {
      setCompatibleItem('cococv_current', 'res_new_1');
      expect(localStorage.getItem('cococv_current')).toBe('res_new_1');
    });

    it('syncs optional legacy keys when requested', () => {
      setCompatibleItem('cococv_current', 'res_new_1', ['resume_current', 'resume-agent-current']);
      expect(localStorage.getItem('cococv_current')).toBe('res_new_1');
      expect(localStorage.getItem('resume_current')).toBe('res_new_1');
      expect(localStorage.getItem('resume-agent-current')).toBe('res_new_1');
    });
  });

  describe('removeCompatibleItem', () => {
    it('removes modern key and specified legacy keys', () => {
      localStorage.setItem('cococv_current', 'res_1');
      localStorage.setItem('resume_current', 'res_1');
      localStorage.setItem('resume-agent-current', 'res_1');

      removeCompatibleItem('cococv_current', ['resume_current', 'resume-agent-current']);

      expect(localStorage.getItem('cococv_current')).toBeNull();
      expect(localStorage.getItem('resume_current')).toBeNull();
      expect(localStorage.getItem('resume-agent-current')).toBeNull();
    });

    it('removes default mapped legacy keys when legacyKeys parameter is omitted', () => {
      localStorage.setItem('cococv_resumes', '["res_1"]');
      localStorage.setItem('resume_resumes', '["res_1"]');

      removeCompatibleItem('cococv_resumes');

      expect(localStorage.getItem('cococv_resumes')).toBeNull();
      expect(localStorage.getItem('resume_resumes')).toBeNull();
    });
  });

  describe('migrateAllRegisteredKeys', () => {
    it('migrates all registered legacy keys in one call', () => {
      localStorage.setItem('resume_resumes', '["res_1", "res_2"]');
      localStorage.setItem('resume_current', 'res_1');
      localStorage.setItem('resume_pinned_ids', '["res_1"]');
      localStorage.setItem('resume_v2_data', '{"title": "老数据"}');

      migrateAllRegisteredKeys();

      expect(localStorage.getItem('cococv_resumes')).toBe('["res_1", "res_2"]');
      expect(localStorage.getItem('cococv_current')).toBe('res_1');
      expect(localStorage.getItem('cococv_pinned_ids')).toBe('["res_1"]');
      expect(localStorage.getItem('cococv_v2_data')).toBe('{"title": "老数据"}');
    });
  });
});
