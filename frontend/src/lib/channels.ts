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
  name_status: string | null;
  coexistence: boolean;
};

export type ChannelsResponse = {
  items: ChannelCard[];
  messenger_available: boolean;
  messenger_limit: number | null;
  messenger_used: number;
  whatsapp_available: boolean;
  whatsapp_limit: number | null;
  whatsapp_used: number;
};

export type WhatsAppConnected = {
  channel_account_id: string;
  display_phone: string | null;
  display_name: string | null;
  name_status: string | null;
  coexistence: boolean;
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

/**
 * Plain-language messages for wizard errors (ONBOARDING_AND_CHANNEL_SETUP.md §6-7). Codes not listed
 * here (e.g. plan_limit_exceeded, permissions_missing) use the server's message, which names the channel.
 */
export const SETUP_ERRORS: Record<string, string> = {
  popup_blocked: "Your browser blocked the Facebook window. Allow pop-ups for this site, then try again.",
  cancelled: "The Facebook window was closed before you finished. Try again when you're ready.",
  no_pages: "No Pages came back from Facebook. You may be logged in with a different Facebook account, or didn't tick a Page.",
  invalid_token: "Facebook didn't confirm your login. Try again.",
  invalid_state: "This connection attempt expired. Start again.",
  setup_expired: "This connection attempt timed out. Start again.",
  page_not_connectable: "One of the Pages you chose can't be connected from this account.",
  channels_not_configured: "This connection isn't switched on yet. We'll let you know when it is.",
  // WhatsApp (ONBOARDING_AND_CHANNEL_SETUP.md §7)
  code_missing: "Facebook didn't finish the sign-up. Start again.",
  waba_not_shared: "Your WhatsApp account wasn't shared with us during sign-up. Start again and keep it selected.",
  number_not_in_account: "That number isn't in the WhatsApp account you chose. Start again.",
  number_connected_elsewhere: "This number is connected to another business on our platform. Contact us.",
  pin_protected:
    "This number is protected by a PIN from an earlier setup. Remove two-step verification in WhatsApp Manager, then try again.",
  subscription_unverified: "WhatsApp didn't confirm the connection. Try again.",
  wa_error: "Facebook reported a problem during sign-up.",
};

/* Facebook JavaScript SDK ------------------------------------------------------------- */

type FBLoginResponse = { status: string; authResponse?: { accessToken?: string; code?: string } | null };

declare global {
  interface Window {
    FB?: {
      init: (options: { appId: string; version: string; xfbml?: boolean; cookie?: boolean }) => void;
      login: (callback: (response: FBLoginResponse) => void, options: Record<string, unknown> & { config_id: string }) => void;
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

export type SignupResult = { code: string; wabaId: string; phoneNumberId: string };

export class SignupStopped extends Error {
  constructor(
    public reason: "cancelled" | "wa_error",
    public step: string | null,
    public detail: string | null,
  ) {
    super(reason);
  }
}

/**
 * WhatsApp Embedded Signup. Meta returns the one-time ``code`` through the login callback and
 * the WhatsApp Business Account + phone number ids through a ``message`` event from facebook.com,
 * in either order. Call directly from a click handler.
 */
export function whatsappSignup(configId: string, mode: "new_number" | "coexistence"): Promise<SignupResult> {
  return new Promise((resolve, reject) => {
    let code: string | null = null;
    let ids: { wabaId: string; phoneNumberId: string } | null = null;
    const finish = () => {
      if (code && ids) {
        window.removeEventListener("message", onMessage);
        resolve({ code, ...ids });
      }
    };
    const stop = (error: SignupStopped) => {
      window.removeEventListener("message", onMessage);
      reject(error);
    };
    function onMessage(event: MessageEvent) {
      // Only trust messages from Facebook's own window.
      let host: string;
      try {
        host = new URL(event.origin).hostname;
      } catch {
        return; // e.g. "null" origin from a sandboxed frame
      }
      if (!/(^|\.)facebook\.com$/.test(host)) return;
      let data: { type?: string; event?: string; data?: Record<string, string> };
      try {
        data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }
      if (data?.type !== "WA_EMBEDDED_SIGNUP") return;
      const info = data.data ?? {};
      if (data.event === "CANCEL") stop(new SignupStopped("cancelled", info.current_step ?? null, null));
      else if (data.event === "ERROR") stop(new SignupStopped("wa_error", null, info.error_message ?? null));
      else if (info.waba_id && info.phone_number_id) {
        ids = { wabaId: info.waba_id, phoneNumberId: info.phone_number_id };
        finish();
      }
    }
    if (!window.FB) {
      reject(new Error("sdk_failed"));
      return;
    }
    window.addEventListener("message", onMessage);
    window.FB.login(
      (response) => {
        const value = response.authResponse?.code;
        if (value) {
          code = value;
          finish();
        } else if (!ids) {
          stop(new SignupStopped("cancelled", null, null));
        }
      },
      {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
        extras: {
          setup: {},
          sessionInfoVersion: "3",
          ...(mode === "coexistence" ? { featureType: "whatsapp_business_app_onboarding" } : {}),
        },
      },
    );
  });
}
