import type { Config } from 'tailwindcss'

// Design tokens verbatim from export/citara.css — the design hand-off source of
// truth, the same hex set ui/theme.py injects for Streamlit. The accent is
// deliberately a CSS var, NOT a hardcoded hex: the active vertical's palette
// (legal #7C9CFF / salud #46CFA6) is swapped on :root at runtime, the same
// pattern inject_theme used in Streamlit (src/index.css holds the defaults).
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#101115',
        bg2: '#0C0D10',
        surface: '#16181E',
        surface2: '#1C1F27',
        elevated: '#222631',
        border: '#282C36',
        'border-strong': '#373C49',
        text: '#ECEEF2',
        muted: '#9CA0AB',
        faint: '#686C77',
        ok: '#46CFA6',
        warn: '#E6A95C',
        'warn-tint': 'rgba(230,169,92,0.13)',
        'warn-line': 'rgba(230,169,92,0.38)',
        accent: 'var(--accent)',
        'accent-on': 'var(--accent-on)',
        'accent-tint': 'var(--accent-tint)',
        'accent-line': 'var(--accent-line)',
      },
      fontFamily: {
        serif: ['"IBM Plex Serif"', 'Georgia', 'serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        sm: '8px', // --r-sm (chips)
        md: '12px', // --r-md (badges, corpus card)
        lg: '18px', // --r-lg
        card: '11px', // .domain-card / suggestion rows
        tile: '34px', // the C¹ splash/loading tile
      },
      // Loading-state keyframes verbatim from export/citara.css (mock 04).
      // citara- prefix: generic names could collide with Tailwind's built-ins.
      keyframes: {
        'citara-dots': {
          '0%,80%,100%': { opacity: '.25', transform: 'translateY(0)' },
          '40%': { opacity: '1', transform: 'translateY(-2px)' },
        },
        'citara-shimmer': {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
        'citara-pulse': {
          '0%,100%': { opacity: '.55' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        'citara-dots': 'citara-dots 1.2s infinite',
        'citara-shimmer': 'citara-shimmer 1.6s linear infinite',
        'citara-pulse': 'citara-pulse 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
