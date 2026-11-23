import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/@tencent-ai/')) return 'cloud-sdk';
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) return 'react-vendor';
          if (id.includes('node_modules/@phosphor-icons/')) return 'icons';
        },
      },
    },
  },
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
