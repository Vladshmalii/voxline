import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Optional same-origin dev setup: VITE_API_URL="" makes the browser call
  // /api on the dev server, which forwards it here (no CORS involved).
  const apiTarget = env.VITE_DEV_PROXY_TARGET || 'http://localhost:8086';

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: { '/api': { target: apiTarget, changeOrigin: true, ws: true } },
    },
    resolve: {
      alias: {
        app: path.resolve(__dirname, 'src/app'),
        components: path.resolve(__dirname, 'src/components'),
        pages: path.resolve(__dirname, 'src/pages'),
        contexts: path.resolve(__dirname, 'src/contexts'),
        i18n: path.resolve(__dirname, 'src/i18n'),
        theme: path.resolve(__dirname, 'src/theme'),
        utils: path.resolve(__dirname, 'src/utils'),
        data: path.resolve(__dirname, 'src/data'),
      },
    },
    build: {
      outDir: 'dist',
    },
  };
});
