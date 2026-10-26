import { createWorkBuddyCloud } from '@tencent-ai/workbuddy-cloud-sdk';

/**
 * WorkBuddy 云服务公开配置。
 *
 * 三个值由部署方在构建时注入（见 .env.example 中的 VITE_WB_* 三项），
 * 源码不内置任何具体环境地址，方便别人用自己的 applicationId 重新开通后替换。
 * 其中 publishableKey 是只绑定合法来源域名的公开标识，不是调用密钥。
 */
const endpoint = (import.meta.env.VITE_WB_ENDPOINT ?? '').replace(/\/$/, '');
const oauthRelayBaseUrl = import.meta.env.VITE_WB_OAUTH_RELAY ?? '';
const publishableKey = import.meta.env.VITE_WB_PUBLISHABLE_KEY ?? '';

export const cloudPublicConfig = { endpoint, oauthRelayBaseUrl, publishableKey };

/** 未配置云服务时为 false，界面应引导去「AI 设置」补齐，而不是直接抛错。 */
export const isCloudConfigured = Boolean(endpoint && publishableKey);

/** 未配置时的占位对象：任何调用都会给出明确的中文原因，避免模块加载即崩溃。 */
function unconfiguredClient(): unknown {
  return new Proxy(Object.create(null), {
    get() {
      throw new Error('尚未配置云服务：请在环境变量中提供 VITE_WB_ENDPOINT 与 VITE_WB_PUBLISHABLE_KEY');
    },
  });
}

/** 全局唯一云服务客户端：Auth / Database / Storage / LLM 四个模块共用。 */
export const cloud = isCloudConfigured
  ? createWorkBuddyCloud(cloudPublicConfig)
  : (unconfiguredClient() as ReturnType<typeof createWorkBuddyCloud>);
