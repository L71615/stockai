/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/renderer/src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 复用 stockai 暗色主题 token
        bg: {
          primary: "oklch(0.18 0.005 250)",
          secondary: "oklch(0.22 0.006 250)",
          tertiary: "oklch(0.26 0.007 250)",
        },
        border: {
          DEFAULT: "oklch(0.32 0.006 250)",
          subtle: "oklch(0.28 0.005 250)",
        },
        fg: {
          DEFAULT: "oklch(0.95 0.005 250)",
          muted: "oklch(0.65 0.008 250)",
          subtle: "oklch(0.50 0.008 250)",
        },
        primary: {
          DEFAULT: "oklch(0.55 0.18 142)",
          fg: "oklch(0.98 0.005 142)",
        },
        success: {
          DEFAULT: "oklch(0.65 0.18 142)",
          fg: "oklch(0.18 0.01 142)",
        },
        warning: {
          DEFAULT: "oklch(0.75 0.15 70)",
          fg: "oklch(0.18 0.01 70)",
        },
        danger: {
          DEFAULT: "oklch(0.62 0.22 25)",
          fg: "oklch(0.98 0.005 25)",
        },
        muted: {
          DEFAULT: "oklch(0.30 0.005 250)",
          fg: "oklch(0.65 0.008 250)",
        },
      },
      fontFamily: {
        sans: [
          "PingFang SC",
          "Microsoft YaHei",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "SF Mono",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        none: "0",
      },
    },
  },
  plugins: [],
}
