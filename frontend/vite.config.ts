import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import pwaBuild from './pwa-build.mjs';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(),tailwindcss(),pwaBuild()],server:{proxy:{'/api':'http://127.0.0.1:8000'}}});
