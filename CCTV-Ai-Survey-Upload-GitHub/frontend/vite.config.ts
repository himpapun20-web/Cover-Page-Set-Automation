import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: 'frontend',
  publicDir: '../public',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq, req) => {
            const forwarded = req.headers['x-forwarded-proto'];
            const protocol = forwarded ? String(forwarded).split(',')[0].trim() : ((req.socket as { encrypted?: boolean }).encrypted ? 'https' : 'http');
            const host = req.headers['x-forwarded-host'] || req.headers.host;
            if (host) proxyReq.setHeader('x-forwarded-host', host);
            proxyReq.setHeader('x-forwarded-proto', protocol);
          });
        },
      },
    },
  },
  build: { outDir: '../dist', emptyOutDir: true },
});
