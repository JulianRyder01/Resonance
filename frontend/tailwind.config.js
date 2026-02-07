/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 白色科技风基调
        background: "#f8fafc", // Slate-50, 极浅灰白
        surface: "#ffffff",    // 纯白卡片
        
        // 文字层级
        "text-primary": "#0f172a", // Slate-900
        "text-secondary": "#64748b", // Slate-500
        
        // 科技蓝主色调
        primary: "#3b82f6", // Blue-500
        "primary-hover": "#2563eb",
        "primary-light": "#eff6ff", // Blue-50
        
        // 辅助色
        accent: "#8b5cf6", // Violet
        danger: "#ef4444",
        success: "#10b981",
        
        // 边框
        border: "#e2e8f0", // Slate-200
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      boxShadow: {
        'soft': '0 4px 20px -2px rgba(0, 0, 0, 0.05)',
        'glow': '0 0 15px rgba(59, 130, 246, 0.3)',
      }
    },
  },
  plugins: [],
  darkMode: 'class', // 手动控制暗色，默认我们做亮色
}