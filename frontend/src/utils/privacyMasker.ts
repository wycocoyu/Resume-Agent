/**
 * Client-Side PII Masking & De-identification Utility
 * 
 * Implements deterministic tokenization and reversible re-hydration
 * for candidate privacy protection (Issue #56).
 */

export interface PIIMapping {
  tokenToReal: Record<string, string>;
  realToToken: Record<string, string>;
  counters: Record<string, number>;
}

export interface MaskOptions {
  candidateName?: string;
  seedKnownFields?: boolean;
}

export interface MaskResult<T = unknown> {
  masked: T;
  maskedData: T;
  tokenMap: Record<string, string>;
  mapping: PIIMapping;
}

export interface MaskState {
  tokenToReal: Record<string, string>;
  realToToken: Record<string, string>;
  counters: Record<string, number>;
}

function createMaskState(): MaskState {
  return {
    tokenToReal: {},
    realToToken: {},
    counters: {
      NAME: 0,
      PHONE: 0,
      EMAIL: 0,
      IDCARD: 0,
      ADDRESS: 0,
    },
  };
}

function getOrCreateToken(category: string, realValue: string, state: MaskState): string {
  const trimmed = realValue.trim();
  if (!trimmed) return realValue;

  if (state.realToToken[trimmed]) {
    return state.realToToken[trimmed];
  }

  if (state.counters[category] === undefined) {
    state.counters[category] = 0;
  }
  state.counters[category] += 1;
  const token = `{{${category}_${state.counters[category]}}}`;
  state.realToToken[trimmed] = token;
  state.tokenToReal[token] = trimmed;
  return token;
}

const CHINESE_PHONE_REGEX = /(?<!\d)(?:\+?86[- ]?)?(1[3-9]\d{9})(?!\d)/g;
const EMAIL_REGEX = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
const IDCARD_REGEX = /(?<!\d)([1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])(?!\d)/g;
const ADDRESS_REGEX = /(?:(?:北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆|香港|澳门)(?:省|市|自治区)?[\u4e00-\u9fa5\d]{2,25}?(?:区|县|街道|路|弄|号|栋|室|大厦|园|城|院|里)(?:[\u4e00-\u9fa5\d]+(?:号|栋|室|院|里|层|座))?)/g;

/**
 * Masks text containing sensitive PII and updates the deterministic mapping.
 */
export function maskTextPII(
  text: string,
  state: MaskState = createMaskState(),
  options?: MaskOptions
): { masked: string; mapping: PIIMapping; tokenMap: Record<string, string> } {
  if (text === null || text === undefined) {
    return {
      masked: text,
      mapping: {
        tokenToReal: state.tokenToReal,
        realToToken: state.realToToken,
        counters: state.counters,
      },
      tokenMap: state.tokenToReal,
    };
  }

  if (typeof text !== 'string' || text.length === 0) {
    return {
      masked: text,
      mapping: {
        tokenToReal: state.tokenToReal,
        realToToken: state.realToToken,
        counters: state.counters,
      },
      tokenMap: state.tokenToReal,
    };
  }

  // 1. Explicit Candidate Name if provided
  if (options?.candidateName && options.candidateName.trim()) {
    getOrCreateToken('NAME', options.candidateName.trim(), state);
  }

  // Pre-seed known real-to-token replacements sorted by length descending
  let currentText = text;

  // Replace candidate names first if registered
  const registeredNames = Object.entries(state.realToToken).filter(([_, token]) =>
    token.startsWith('{{NAME_')
  );
  for (const [realVal, token] of registeredNames) {
    if (realVal && currentText.includes(realVal)) {
      currentText = currentText.replaceAll(realVal, token);
    }
  }

  // 2. Mobile phones
  currentText = currentText.replace(CHINESE_PHONE_REGEX, (match, p1) => {
    // If the match was whole phone number e.g. 13800138000
    // Use the 11-digit phone number as key if match equals p1, or full match if prefixed
    const key = match.trim();
    return getOrCreateToken('PHONE', key, state);
  });

  // 3. Email addresses
  currentText = currentText.replace(EMAIL_REGEX, (match) => {
    return getOrCreateToken('EMAIL', match.trim(), state);
  });

  // 4. Resident ID cards (18-digit)
  currentText = currentText.replace(IDCARD_REGEX, (match) => {
    return getOrCreateToken('IDCARD', match.trim(), state);
  });

  // 5. Addresses
  currentText = currentText.replace(ADDRESS_REGEX, (match) => {
    return getOrCreateToken('ADDRESS', match.trim(), state);
  });

  // Also replace any previously registered tokens (like addresses, names seeded earlier)
  const remainingRegistrations = Object.entries(state.realToToken).sort(
    (a, b) => b[0].length - a[0].length
  );
  for (const [realVal, token] of remainingRegistrations) {
    if (realVal && currentText.includes(realVal)) {
      currentText = currentText.replaceAll(realVal, token);
    }
  }

  return {
    masked: currentText,
    mapping: {
      tokenToReal: state.tokenToReal,
      realToToken: state.realToToken,
      counters: state.counters,
    },
    tokenMap: state.tokenToReal,
  };
}

/**
 * Unmasks a text string by replacing placeholder tokens with original real values.
 */
export function unmaskTextPII(
  text: string,
  mapping: PIIMapping | Record<string, string>
): string {
  if (text === null || text === undefined || typeof text !== 'string') {
    return text;
  }

  const tokenToReal =
    'tokenToReal' in mapping ? (mapping as PIIMapping).tokenToReal : (mapping as Record<string, string>);

  return text.replace(/\{\{([A-Z]+_\d+)\}\}/g, (match) => {
    return tokenToReal[match] !== undefined ? tokenToReal[match] : match;
  });
}

/**
 * Mask PII in text strings or structured resume data objects.
 */
export function maskResumePII<T = unknown>(
  target: T,
  options?: MaskOptions
): MaskResult<T> {
  const state = createMaskState();

  if (target === null || target === undefined) {
    return {
      masked: target,
      maskedData: target,
      tokenMap: state.tokenToReal,
      mapping: {
        tokenToReal: state.tokenToReal,
        realToToken: state.realToToken,
        counters: state.counters,
      },
    };
  }

  if (typeof target === 'string') {
    const res = maskTextPII(target, state, options);
    return {
      masked: res.masked as unknown as T,
      maskedData: res.masked as unknown as T,
      tokenMap: state.tokenToReal,
      mapping: res.mapping,
    };
  }

  // Deep clone structured object
  const clone = structuredClone(target) as Record<string, any>;

  // Pre-seed structured candidate fields if present
  const basic = clone.basic || clone.contact || {};
  const candidateName =
    options?.candidateName || clone.name || basic.name || (clone.info && clone.info.name);
  if (candidateName && typeof candidateName === 'string' && candidateName.trim()) {
    getOrCreateToken('NAME', candidateName.trim(), state);
  }

  const phone = clone.phone || basic.phone || (clone.info && clone.info.phone);
  if (phone && typeof phone === 'string' && phone.trim()) {
    getOrCreateToken('PHONE', phone.trim(), state);
  }

  const email = clone.email || basic.email || (clone.info && clone.info.email);
  if (email && typeof email === 'string' && email.trim()) {
    getOrCreateToken('EMAIL', email.trim(), state);
  }

  const location =
    clone.location || clone.address || basic.location || basic.address || (clone.info && clone.info.location);
  if (location && typeof location === 'string' && location.trim()) {
    getOrCreateToken('ADDRESS', location.trim(), state);
  }

  // Recursive traversal to mask all strings
  function maskDeep(val: any): any {
    if (val === null || val === undefined) return val;
    if (typeof val === 'string') {
      return maskTextPII(val, state, options).masked;
    }
    if (Array.isArray(val)) {
      return val.map((item) => maskDeep(item));
    }
    if (typeof val === 'object') {
      const result: Record<string, any> = {};
      for (const key of Object.keys(val)) {
        result[key] = maskDeep(val[key]);
      }
      return result;
    }
    return val;
  }

  const maskedObj = maskDeep(clone) as T;

  return {
    masked: maskedObj,
    maskedData: maskedObj,
    tokenMap: state.tokenToReal,
    mapping: {
      tokenToReal: state.tokenToReal,
      realToToken: state.realToToken,
      counters: state.counters,
    },
  };
}

/**
 * Re-hydrates / unmasks placeholder tokens in a string or structured resume object.
 */
export function unmaskResumePII<T = unknown>(
  target: T,
  mapping: PIIMapping | Record<string, string>
): T {
  if (target === null || target === undefined) {
    return target;
  }

  if (typeof target === 'string') {
    return unmaskTextPII(target, mapping) as unknown as T;
  }

  const tokenToReal =
    'tokenToReal' in mapping ? (mapping as PIIMapping).tokenToReal : (mapping as Record<string, string>);

  function unmaskDeep(val: any): any {
    if (val === null || val === undefined) return val;
    if (typeof val === 'string') {
      return unmaskTextPII(val, tokenToReal);
    }
    if (Array.isArray(val)) {
      return val.map((item) => unmaskDeep(item));
    }
    if (typeof val === 'object') {
      const result: Record<string, any> = {};
      for (const key of Object.keys(val)) {
        result[key] = unmaskDeep(val[key]);
      }
      return result;
    }
    return val;
  }

  return unmaskDeep(structuredClone(target)) as T;
}

/**
 * Generates safe masked API key preview matching backend _mask_key logic.
 */
export function maskApiKey(raw?: string | null): string {
  const val = (raw || '').trim();
  if (!val) {
    return '';
  }
  if (val.length > 12) {
    return `${val.slice(0, 8)}••••••${val.slice(-4)}`;
  }
  if (val.length > 6) {
    return `${val.slice(0, 4)}••••${val.slice(-2)}`;
  }
  return `${val.slice(0, 2)}•••`;
}
