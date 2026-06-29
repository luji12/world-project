/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        abyss: {
          900: '#171712', // 深色书库底色
          950: '#0f100c', // 墨黑外框
        },
        primary: {
          400: '#c45a48', // 朱砂高光
          500: '#ad4b3a', // 朱砂主色
        },
        glow: {
          amber: 'rgba(245, 158, 11, 0.4)',
          indigo: 'rgba(99, 102, 241, 0.4)',
        }
      },
      backgroundImage: {
        'nebula-gradient': 'radial-gradient(ellipse at 18% 0%, #2a291d 0%, #0f100c 62%)',
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'fade-in': 'fadeIn 0.3s ease-out forwards',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite alternate',
      },
      keyframes: {
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        glowPulse: {
          '0%': { boxShadow: '0 0 10px rgba(200,149,79,0.08)' },
          '100%': { boxShadow: '0 0 20px rgba(200,149,79,0.18)' },
        }
      }
    },
  },
  plugins: [],
}
