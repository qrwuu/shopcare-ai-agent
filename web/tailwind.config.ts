import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: {
          base:    "#081735",
          surface: "#0F1F45",
          raised:  "#132A5A",
        },
        accent: {
          DEFAULT: "#7DD3FC",
          light:   "#BAE6FD",
          subtle:  "#0A1A30",
        },
        "text-col": {
          primary:   "#F4F4F6",
          secondary: "#A3B4D1",
          tertiary:  "#5A7099",
        },
        "border-col": {
          DEFAULT: "#1A3060",
          subtle:  "#0F1F45",
        },
        success: "#10B981",
        warning: "#F59E0B",
        danger:  "#EF4444",
      },
      fontFamily: {
        display: ["var(--font-display)", "Noto Serif CJK SC", "Noto Sans CJK SC", "SimSun", "serif"],
        body:    ["var(--font-body)", "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", "sans-serif"],
        mono:    ["var(--font-mono)", "Noto Sans Mono CJK SC", "Noto Sans CJK SC", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
