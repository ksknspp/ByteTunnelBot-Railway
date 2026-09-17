const BASE_URL =
  "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main";

const CHANNEL = "@ByteTunnel";

const MENU = {
  keyboard: [
    ["⚡ دریافت کانفیگ", "📦 دریافت همه"],
    ["🌐 Proxy", "🏆 بهترین 100"],
    ["🌍 کشورها", "🔌 پروتکل‌ها"],
    ["📊 آمار"],
  ],
  resize_keyboard: true,
};

function tgUrl(env, method) {
  return `https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`;
}

async function tg(env, method, body = {}) {
  const r = await fetch(tgUrl(env, method), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

  return r.json();
}

async function sendMessage(env, chatId, text, extra = {}) {
  return tg(env, "sendMessage", {
    chat_id: chatId,
    text,
    ...extra,
  });
}

async function answerCallback(env, id, text = "") {
  return tg(env, "answerCallbackQuery", {
    callback_query_id: id,
    text,
  });
}

async function isMember(env, userId) {
  try {
    const result = await tg(env, "getChatMember", {
      chat_id: CHANNEL,
      user_id: userId,
    });

    if (!result.ok) return false;

    return ["creator", "administrator", "member"].includes(
      result.result.status
    );
  } catch {
    return false;
  }
}

function joinKeyboard() {
  return {
    inline_keyboard: [
      [
        {
          text: "📢 عضویت در @ByteTunnel",
          url: "https://t.me/ByteTunnel",
        },
      ],
    ],
  };
}

async function requireJoin(env, message) {
  const userId = message.from?.id;

  if (!userId) return true;

  const ok = await isMember(env, userId);

  if (ok) return true;

  await sendMessage(
    env,
    message.chat.id,
    "🔒 برای استفاده از ByteTunnel ابتدا در کانال @ByteTunnel عضو شوید.",
    {
      reply_markup: joinKeyboard(),
    }
  );

  return false;
}

async function fetchText(path) {
  const r = await fetch(`${BASE_URL}/${path}`, {
    cf: {
      cacheTtl: 300,
      cacheEverything: true,
    },
  });

  if (!r.ok) {
    throw new Error(`GitHub HTTP ${r.status}`);
  }

  return r.text();
}

function parseConfigs(text) {
  return text
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter((x) => /^(vless|vmess|trojan|ss|ssr|hysteria2|hy2|tuic):\/\//i.test(x));
}

function cleanConfig(config) {
  config = config.trim();

  if (!config.includes("#")) {
    return config;
  }

  const [base, ...parts] = config.split("#");
  const fragment = parts.join("#");

  const flags = fragment.match(/[\u{1F1E6}-\u{1F1FF}]{2}/gu);

  if (flags?.length) {
    return `${base}#${flags[0]}`;
  }

  return base;
}

function configCard(number, config) {
  return `#${number}\n${cleanConfig(config)}`;
}

async function getVerified() {
  return parseConfigs(await fetchText("verified/configs.txt"));
}

async function getTop100() {
  return parseConfigs(await fetchText("top100.txt"));
}

async function sendTop100(env, chatId) {
  try {
    const verified = await getVerified();
    const top = await getTop100();

    const items = top.slice(0, 10);

    const lines = [
      "⚡ ByteTunnel",
      "",
      `🟢 موجود: ${verified.length}`,
      `📦 ارسال: ${items.length}`,
      "",
    ];

    items.forEach((config, i) => {
      lines.push(configCard(i + 1, config));
      lines.push("");
    });

    await sendMessage(env, chatId, lines.join("\n"));
  } catch (e) {
    await sendMessage(
      env,
      chatId,
      "❌ دریافت لیست کانفیگ‌ها با خطا مواجه شد."
    );
  }
}

async function sendOneConfig(env, chatId) {
  try {
    const configs = await getVerified();

    if (!configs.length) {
      await sendMessage(env, chatId, "❌ کانفیگی پیدا نشد.");
      return;
    }

    const config =
      configs[Math.floor(Math.random() * configs.length)];

    await sendMessage(env, chatId, cleanConfig(config));
  } catch {
    await sendMessage(
      env,
      chatId,
      "❌ دریافت کانفیگ با خطا مواجه شد."
    );
  }
}

async function sendAll(env, chatId) {
  try {
    const configs = parseConfigs(
      await fetchText("all/configs.txt")
    );

    if (!configs.length) {
      await sendMessage(env, chatId, "❌ کانفیگی پیدا نشد.");
      return;
    }

    const text = configs.map(cleanConfig).join("\n");

    // Telegram message limit
    const chunkSize = 3800;

    for (let i = 0; i < text.length; i += chunkSize) {
      await sendMessage(
        env,
        chatId,
        text.slice(i, i + chunkSize)
      );
    }
  } catch {
    await sendMessage(
      env,
      chatId,
      "❌ دریافت همه کانفیگ‌ها با خطا مواجه شد."
    );
  }
}

async function showStats(env, chatId) {
  try {
    const configs = await getVerified();

    await sendMessage(
      env,
      chatId,
      [
        "📊 آمار ByteTunnel",
        "",
        `🟢 کانفیگ‌های معتبر: ${configs.length}`,
        "🌐 منبع: Free-v2ray-Configs",
      ].join("\n")
    );
  } catch {
    await sendMessage(env, chatId, "❌ دریافت آمار ناموفق بود.");
  }
}

async function handleMessage(env, message) {
  if (!message?.chat?.id) return;

  const chatId = message.chat.id;
  const text = message.text || "";

  if (!(await requireJoin(env, message))) {
    return;
  }

  if (text === "/start") {
    await sendMessage(
      env,
      chatId,
      "⚡ ByteTunnel\n\nبه ربات دریافت کانفیگ خوش آمدید.",
      {
        reply_markup: MENU,
      }
    );
    return;
  }

  if (text === "⚡ دریافت کانفیگ") {
    await sendOneConfig(env, chatId);
    return;
  }

  if (text === "📦 دریافت همه") {
    await sendAll(env, chatId);
    return;
  }

  if (text === "🏆 بهترین 100") {
    await sendTop100(env, chatId);
    return;
  }

  if (text === "📊 آمار") {
    await showStats(env, chatId);
    return;
  }

  if (text === "🌐 Proxy") {
    await sendMessage(
      env,
      chatId,
      "🌐 بخش Proxy در نسخه Cloudflare در مرحله بعد اضافه می‌شود."
    );
    return;
  }

  if (text === "🌍 کشورها") {
    await sendMessage(
      env,
      chatId,
      "🌍 بخش کشورها در مرحله بعد اضافه می‌شود."
    );
    return;
  }

  if (text === "🔌 پروتکل‌ها") {
    await sendMessage(
      env,
      chatId,
      "🔌 بخش پروتکل‌ها در مرحله بعد اضافه می‌شود."
    );
    return;
  }

  if (text === "/admin") {
    const admins = String(env.ADMIN_IDS || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);

    if (admins.includes(String(message.from?.id))) {
      await sendMessage(
        env,
        chatId,
        "👑 پنل مدیریت\n\nنسخه Cloudflare Worker فعال است."
      );
    }

    return;
  }
}


async function setupWebhook(request, env) {
  const url = new URL(request.url);
  const key = url.searchParams.get("key");

  if (!key || key !== env.SETUP_KEY) {
    return new Response("Unauthorized", { status: 401 });
  }

  const webhookUrl = `${url.origin}/telegram`;

  const r = await fetch(
    `https://api.telegram.org/bot${env.BOT_TOKEN}/setWebhook`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: webhookUrl,
        drop_pending_updates: true
      })
    }
  );

  const data = await r.text();

  return new Response(data, {
    status: r.status,
    headers: { "Content-Type": "application/json" }
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/setup-webhook") {
      return setupWebhook(request, env);
    }

    if (request.method === "GET") {
      return new Response(
        "⚡ ByteTunnel Worker OK",
        {
          status: 200,
          headers: {
            "content-type": "text/plain; charset=UTF-8",
          },
        }
      );
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", {
        status: 405,
      });
    }

    if (env.WEBHOOK_SECRET) {
      const received =
        request.headers.get("X-Telegram-Bot-Api-Secret-Token");

      if (received !== env.WEBHOOK_SECRET) {
        return new Response("Unauthorized", {
          status: 401,
        });
      }
    }

    try {
      const update = await request.json();

      if (update.message) {
        ctx.waitUntil(handleMessage(env, update.message));
      }

      if (update.callback_query) {
        await answerCallback(env, update.callback_query.id);
      }

      return new Response("OK");
    } catch (error) {
      console.error(error);
      return new Response("OK");
    }
  },
};
