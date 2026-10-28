"use client";

export type ChannelCard = {
  id: string;
  provider: "whatsapp" | "messenger";
  name: string | null;
  display_phone: string | null;
  picture: string | null;
  status: "connected" | "disconnected" | "error";
  health_status: "healthy" | "pending" | "action_needed" | "disconnected";
  health_reason: string | null;
  last_webhook_at: string | null;
  messages_today: number;
};

export type ChannelsResponse = {
  items: ChannelCard[];
  messenger_available: boolean;
  messenger_limit: number | null;
  messenger_used: number;
};

export type SetupStarted = {
  id: string;
  state: string;
  expires_at: string;
  app_id: string;
  login_config_id: string;
  graph_api_version: string;
};

export type PageOption = {
  id: string;
  name: string;
  picture: string | null;
  status: "connectable" | "connected_here" | "connected_elsewhere" | "needs_full_control";
};

export type Authorized = { pages: PageOption[]; limit: number | null; used: number };

export type PageResult = {
  page_id: string;
  name: string;
  ok: boolean;
  channel_account_id: string | null;
  error_code: string | null;
  message: string | null;
};

/** Plain-language messages for wizard errors (ONBOARDING_AND_CHANNEL_SETUP.md §6). */
export const SETUP_ERRORS: Record<string, string> = {
  popup_blocked: "Your browser blocked the Facebook window. Allow pop-ups for this site, then try again.",
  cancelled: "The Facebook window was closed before you finished. Try again when you're ready.",
  no_pages: "No Pages came back from Facebook. You may be logged in with a different Facebook account, or didn't tick a Page.",
  permissions_missing: "We need permission to manage messages for your Page. Try again and keep all permissions switched on.",
  invalid_token: "Facebook didn't confirm your login. Try again.",
  invalid_state: "This connection attempt expired. Start again.",
  setup_expired: "This connection attempt timed out. Start again.",
  plan_limit_exceeded: "Your package doesn't allow more Facebook Pages. Ask us about upgrading.",
  page_not_connectable: "One of the Pages you chose can't be connected from this account.",
  channels_not_configured: "Facebook connection isn't switched on yet. We'll let you know when it is.",
};

/* Facebook JavaScript SDK ------------------------------------------------------------- */

type FBLoginResponse = { status: string; authResponse?: { accessToken?: string } | null };

declare global {
  interface Window {
    FB?: {
      init: (options: { appId: string; version: string; xfbml?: boolean; cookie?: boolean }) => void;
      login: (callback: (response: FBLoginResponse) => void, options: { config_id: string; scope?: string }) => void;
    };
    fbAsyncInit?: () => void;
  }
}

let sdkPromise: Promise<void> | null = null;

/** Load and initialise Meta's SDK once. Must finish before the user clicks, or pop-up blockers stop the login window. */
export function loadFacebookSdk(appId: string, version: string): Promise<void> {
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB?.init({ appId, version, xfbml: false, cookie: false });
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => {
      sdkPromise = null;
      reject(new Error("sdk_failed"));
    };
    document.body.appendChild(script);
  });
  return sdkPromise;
}

/** Opens Facebook Login for Business. Call directly from a click handler. */
export function facebookLogin(configId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!window.FB) {
      reject(new Error("sdk_failed"));
      return;
    }
    window.FB.login(
      (response) => {
        const token = response.authResponse?.accessToken;
        if (token) resolve(token);
        else reject(new Error("cancelled"));
      },
      { config_id: configId },
    );
  });
}
