/** @type {import('tailwindcss').Config} */
import typography from "@tailwindcss/typography";
import plugin from "tailwindcss/plugin";

/** Workspace 换肤变体:data-skin="fresh" 子树内 fresh: 类生效(与 dark: 同构) */
const skinVariant = plugin(({ addVariant }) => {
  addVariant("fresh", '[data-skin="fresh"] &');
});

export default {
  darkMode: ["class"],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        hero: [
          '"Noto Sans SC"',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei UI',
          'Microsoft YaHei',
          'sans-serif',
        ],
        chat: [
          '"Noto Sans SC"',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei UI',
          'sans-serif',
        ],
        // 优雅中文衬线（标题用，参考 Manus）：Mac 优先 Songti SC
        serifcn: [
          '"Songti SC"',
          '"STSong"',
          '"Source Han Serif SC"',
          '"Noto Serif SC"',
          'SimSun',
          'serif',
        ],
      },
      colors: {
        // chat-* 语义 token 变量化（2026-07-16 皮肤覆盖 AI 助手/我的简历页）：
        // 默认值 = NEO 皮肤原值；[data-skin="fresh"] 在 tailwind.css 里改写
        // 变量即可让 275+ 处 chat-* 类一次换肤，无需逐组件写 fresh: 变体
        chat: {
          canvas: 'var(--chat-canvas, #F0F0E8)',
          ink: 'var(--chat-ink, #0A0A0A)',
          'ink-muted': 'var(--chat-ink-muted, #5C6368)',
          accent: 'var(--chat-accent, #4285F4)',
          'accent-deep': 'var(--chat-accent-deep, #3367D6)',
          'user-bubble': 'var(--chat-user-bubble, #D7E7FF)',
          surface: 'var(--chat-surface, #FFFFFF)',
          border: 'var(--chat-border, #000000)',
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      typography: {
        DEFAULT: {
          css: {
            'ul::marker': {
              color: '#000000',
            },
            'ol::marker': {
              color: '#000000',
            },
          },
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        paper: '0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 4px 24px 0 rgba(0, 0, 0, 0.08)',
        'paper-elevated': '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 10px 30px -3px rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
        floating: '0 8px 32px 0 rgba(0, 0, 0, 0.12), 0 2px 8px 0 rgba(0, 0, 0, 0.06)',
        'glow-emerald': '0 0 14px -1px rgba(16, 185, 129, 0.45)',
        'glow-amber': '0 0 14px -1px rgba(245, 158, 11, 0.45)',
        'glow-rose': '0 0 14px -1px rgba(244, 63, 94, 0.45)',
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        'status-pulse': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.65', transform: 'scale(0.95)' },
        },
        'ping-slow': {
          '0%': { transform: 'scale(1)', opacity: '0.75' },
          '70%, 100%': { transform: 'scale(2.2)', opacity: '0' },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        'status-pulse': 'status-pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ping-slow': 'ping-slow 2.5s cubic-bezier(0, 0, 0.2, 1) infinite',
      },
    },
  },
  plugins: [typography, skinVariant],
}

