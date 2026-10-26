import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.YUEJI_API_TARGET || 'http://127.0.0.1:8000',
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const host = req.headers?.host;
            if (host) proxyReq.setHeader('x-yueji-origin-host', host);
          });
        },
      },
    },
  },
});
