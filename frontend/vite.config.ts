import { defineConfig } from 'vite';
import reactSwc from '@vitejs/plugin-react-swc';
import path from 'path';

export default defineConfig({
  plugins: [reactSwc()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    port: 5174,
    proxy: {
      // KRX 데이터 API — krxdata.co.kr 경유
      '/api': {
        target: 'https://krxdata.co.kr',
        changeOrigin: true,
      },
    },
  },
});
