/// <reference types="vite/client" />

/** 构建时注入的云服务公开三项（见 .env.example）。 */
interface ImportMetaEnv {
  readonly VITE_WB_ENDPOINT?: string;
  readonly VITE_WB_OAUTH_RELAY?: string;
  readonly VITE_WB_PUBLISHABLE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
