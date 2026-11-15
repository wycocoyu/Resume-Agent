// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import {
  maskResumePII,
  unmaskResumePII,
  maskApiKey,
  maskTextPII,
  unmaskTextPII,
} from './privacyMasker';

describe('privacyMasker', () => {
  it('masks Chinese mobile phone numbers correctly', () => {
    const raw = '我的手机号是 13800138000，备用联系方式 13912345678。';
    const { masked, tokenMap } = maskResumePII(raw);
    expect(masked).not.toContain('13800138000');
    expect(masked).toContain('{{PHONE_1}}');
    expect(masked).toContain('{{PHONE_2}}');
    expect(tokenMap['{{PHONE_1}}']).toBe('13800138000');
  });

  it('masks email addresses accurately', () => {
    const raw = '发送邮件至 candidate.work@cococv.com 咨询';
    const { masked, tokenMap } = maskResumePII(raw);
    expect(masked).not.toContain('candidate.work@cococv.com');
    expect(masked).toContain('{{EMAIL_1}}');
    expect(tokenMap['{{EMAIL_1}}']).toBe('candidate.work@cococv.com');
  });

  it('masks 18-digit Chinese resident ID cards', () => {
    const raw = '身份证号：11010119900307234X 已核验';
    const { masked, tokenMap } = maskResumePII(raw);
    expect(masked).not.toContain('11010119900307234X');
    expect(masked).toContain('{{IDCARD_1}}');
    expect(tokenMap['{{IDCARD_1}}']).toBe('11010119900307234X');
  });

  it('masks detailed street addresses', () => {
    const raw = '现居地：北京市海淀区中关村南大街1号院';
    const { masked, tokenMap } = maskResumePII(raw);
    expect(masked).not.toContain('北京市海淀区中关村南大街1号院');
    expect(masked).toContain('{{ADDRESS_1}}');
  });

  it('masks candidate name when provided', () => {
    const raw = '候选人 张三 拥有多年分布式研发经验。张三 曾主导核心系统重构。';
    const { masked, tokenMap } = maskResumePII(raw, { candidateName: '张三' });
    expect(masked).not.toContain('张三');
    expect(masked).toBe('候选人 {{NAME_1}} 拥有多年分布式研发经验。{{NAME_1}} 曾主导核心系统重构。');
    expect(tokenMap['{{NAME_1}}']).toBe('张三');
  });

  it('handles structured resume object recursively', () => {
    const resumeObj = {
      basic: {
        name: '李四',
        phone: '13812345678',
        email: 'lisi@example.com',
        location: '上海市浦东新区张江高科',
      },
      summary: '我是李四，电话 13812345678。',
    };
    const { maskedData, tokenMap } = maskResumePII(resumeObj);
    expect(maskedData.basic.name).toBe('{{NAME_1}}');
    expect(maskedData.basic.phone).toBe('{{PHONE_1}}');
    expect(maskedData.basic.email).toBe('{{EMAIL_1}}');
    expect(maskedData.summary).toContain('{{NAME_1}}');
    expect(maskedData.summary).toContain('{{PHONE_1}}');
  });

  it('deduplicates identical PII values to the same placeholder token', () => {
    const raw = '手机一：13800000000，手机二：13800000000';
    const { masked, tokenMap } = maskResumePII(raw);
    expect(masked).toBe('手机一：{{PHONE_1}}，手机二：{{PHONE_1}}');
    expect(Object.keys(tokenMap).length).toBe(1);
  });

  it('does not falsely mask standard dates or non-phone numbers', () => {
    const raw = '发布于 2026-11-15，日访问量 10000000000 次';
    const { masked } = maskResumePII(raw);
    expect(masked).toContain('2026-11-15');
    expect(masked).toContain('10000000000');
  });

  it('unmasks text completely and losslessly', () => {
    const raw = '张三的邮箱是 zhangsan@cococv.com，电话是 13800138000。';
    const { masked, tokenMap } = maskResumePII(raw, { candidateName: '张三' });
    const restored = unmaskResumePII(masked, tokenMap);
    expect(restored).toBe(raw);
  });

  it('unmasks structured objects losslessly', () => {
    const obj = {
      title: '王五的简历',
      contact: '邮箱 wangwu@test.com 电话 13900001111',
    };
    const { maskedData, tokenMap } = maskResumePII(obj, { candidateName: '王五' });
    const restored = unmaskResumePII(maskedData, tokenMap);
    expect(restored).toEqual(obj);
  });

  it('gracefully handles empty inputs and text without PII', () => {
    expect(maskResumePII('').masked).toBe('');
    expect(maskResumePII(null).masked).toBeNull();
    const cleanText = '精通 React 与 TypeScript 架构设计。';
    const { masked, tokenMap } = maskResumePII(cleanText);
    expect(masked).toBe(cleanText);
    expect(Object.keys(tokenMap).length).toBe(0);
  });

  it('masks API keys securely across various boundary lengths', () => {
    expect(maskApiKey('')).toBe('');
    expect(maskApiKey('123')).toBe('12•••');
    expect(maskApiKey('123456')).toBe('12•••');
    expect(maskApiKey('1234567')).toBe('1234••••67');
    expect(maskApiKey('123456789012')).toBe('1234••••12');
    expect(maskApiKey('sk-deepseek-1234567890abcdef')).toBe('sk-deeps••••••cdef');
  });

  it('supports maskTextPII and unmaskTextPII direct calls', () => {
    const text = '联系电话 13712345678';
    const res = maskTextPII(text);
    expect(res.masked).toContain('{{PHONE_1}}');
    const restored = unmaskTextPII(res.masked, res.mapping);
    expect(restored).toBe(text);
  });
});
