#!/data/data/com.termux/files/usr/bin/bash
clear
echo "======================================"
echo "  ByteTunnel  ·  New Layout + Blue"
echo "======================================"
echo
read -p "Cloudflare API Token: " API_TOKEN
[ -z "$API_TOKEN" ] && echo "توکن خالیه" && exit 1

RAND=$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 6)
WORKER_NAME="bt-${RAND}"
DB_NAME="btdb-${RAND}"

ACCOUNTS=$(curl -s -X GET "https://api.cloudflare.com/client/v4/accounts" -H "Authorization: Bearer $API_TOKEN")
ACCOUNT_ID=$(echo "$ACCOUNTS" | jq -r '.result[0].id')
if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "null" ]; then echo "خطا در Account ID"; echo "$ACCOUNTS" | jq .; exit 1; fi
echo "✓ Worker: $WORKER_NAME"

cp worker.local.js worker.js
cp schema.local.sql schema.sql
echo "اعمال چیدمان جدید..."

python3 << 'PY'
import re, base64, gzip

with open("worker.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#9ad8ff"/><stop offset="1" stop-color="#3b9dff"/>
  </linearGradient></defs>
  <rect width="64" height="64" rx="16" fill="#000"/>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="none" stroke="url(#g)" stroke-width="2"/>
  <path d="M18 44V20h10.5c7.2 0 11.5 3.6 11.5 9.2 0 5.7-4.4 9.3-11.6 9.3H26v5.5H18zm8-13.2h2.3c3.1 0 5-1.5 5-3.6s-1.9-3.5-5-3.5H26v7.1z" fill="url(#g)"/>
</svg>'''
new_logo = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

LOGIN_CSS = r'''
:root{
  --bg:#000000;--panel:#070b12;--panel-2:#0b1220;--input:#05080f;
  --border:#1a335c;--text:#f2f7ff;--muted:#9bb4d6;--faint:#6d84a6;
  --brand:#8fd4ff;--brand-2:#3ea8ff;--grad:linear-gradient(135deg,#8fd4ff,#3ea8ff);--red:#f87171;
  --r-md:14px;--r-sm:11px;
  --font:"Outfit","Vazirmatn",system-ui,sans-serif;
}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;padding:0;background:#000;color:var(--text);font-family:var(--font);-webkit-font-smoothing:antialiased}
.shell{display:grid;grid-template-columns:1.15fr .85fr;min-height:100vh}
.hero{position:relative;overflow:hidden;padding:48px 52px;display:flex;flex-direction:column;justify-content:center;background:
  radial-gradient(700px 420px at 20% 20%,rgba(62,168,255,.28),transparent 60%),
  radial-gradient(520px 360px at 80% 80%,rgba(143,212,255,.12),transparent 55%),#000}
.hero:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(143,212,255,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(143,212,255,.07) 1px,transparent 1px);background-size:42px 42px;mask-image:radial-gradient(circle at 30% 40%,#000 20%,transparent 75%);pointer-events:none}
.hero-kicker{font-size:12px;letter-spacing:.28em;text-transform:uppercase;color:var(--brand);font-weight:700;margin-bottom:14px}
.hero h2{font-size:42px;line-height:1.05;margin:0 0 14px;font-weight:800;letter-spacing:-.03em}
.hero p{max-width:420px;color:var(--muted);font-size:15px;line-height:1.65;margin:0}
.hero-pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:28px}
.hero-pills span{border:1px solid #1e4b86;background:rgba(62,168,255,.08);color:#cfe9ff;border-radius:99px;padding:6px 12px;font-size:12px;font-weight:600}
.form-side{display:flex;align-items:center;justify-content:center;padding:28px 22px;background:linear-gradient(180deg,#05070c,#000)}
.login-card{width:100%;max-width:420px;background:rgba(7,11,18,.92);border:1px solid #1a335c;border-radius:24px;padding:32px 28px;box-shadow:0 30px 80px -20px rgba(0,0,0,.85);backdrop-filter:blur(18px)}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.brand-mark{width:44px;height:44px;border-radius:14px;background:#000 url("__LOGO__") center/cover no-repeat;border:1px solid rgba(143,212,255,.4);box-shadow:0 10px 26px -8px rgba(62,168,255,.55)}
.brand-name{font-weight:800;font-size:22px;letter-spacing:.02em}
.brand-name small{display:block;font-size:10px;font-weight:600;color:var(--brand);letter-spacing:.22em;margin-top:-2px}
.login-sub{color:var(--muted);font-size:13px;margin:0 0 20px}
.first-run{background:rgba(62,168,255,.1);border:1px solid rgba(143,212,255,.35);border-radius:14px;padding:12px 14px;font-size:12.5px;color:var(--brand);margin-bottom:18px;line-height:1.55}
.field{margin-bottom:15px}
.field label{display:block;font-size:12px;font-weight:600;color:var(--muted);margin-bottom:7px}
.input-wrap{position:relative}
.input-wrap svg{position:absolute;inset-inline-start:12px;top:50%;transform:translateY(-50%);width:16px;height:16px;color:var(--faint);pointer-events:none}
.input{width:100%;background:#05080f;border:1px solid #1a335c;border-radius:12px;color:var(--text);padding:12px 13px;padding-inline-start:38px;font-size:14px;font-family:var(--font);outline:none}
.input:focus{border-color:#8fd4ff;box-shadow:0 0 0 3px rgba(62,168,255,.18)}
.eye{position:absolute;inset-inline-end:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--faint);cursor:pointer;padding:4px;display:flex}
.submit{width:100%;background:var(--grad);color:#001018;font-weight:800;font-size:14.5px;border:none;border-radius:14px;padding:13px;cursor:pointer;box-shadow:0 14px 32px -12px rgba(62,168,255,.7);display:flex;align-items:center;justify-content:center;gap:8px;margin-top:6px}
.submit:hover{filter:brightness(1.06)}
.submit:disabled{opacity:.55}
.error{color:var(--red);font-size:12.5px;text-align:center;min-height:18px;margin:10px 0 2px}
.lang-toggle{position:fixed;top:16px;inset-inline-end:16px;z-index:5;background:#070b12;border:1px solid #1a335c;border-radius:99px;color:var(--muted);padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer;font-family:var(--font)}
.foot{text-align:center;color:var(--faint);font-size:11.5px;margin-top:20px}
.foot a{color:var(--faint);text-decoration:none}
.support-line{text-align:center;margin-top:14px;font-size:12.5px;color:var(--muted);display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap}
.support-line a{color:var(--brand);font-weight:600;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.lnk-ic{width:14px;height:14px;flex:0 0 14px;fill:currentColor}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{width:15px;height:15px;border:2px solid rgba(0,16,24,.35);border-top-color:#001018;border-radius:99px;animation:spin .7s linear infinite}
@media (max-width:860px){
  .shell{grid-template-columns:1fr}
  .hero{min-height:auto;padding:28px 22px 10px}
  .hero h2{font-size:30px}
}
'''

NEW_ROOT = ''':root{
  --bg:#000000;--bg-soft:#05070c;--panel:#070b12;--panel-2:#0b1220;--input:#05080f;
  --border:#1a335c;--border-soft:#12243f;--text:#f2f7ff;--muted:#9bb4d6;--faint:#6d84a6;
  --brand:#8fd4ff;--brand-2:#3ea8ff;--grad:linear-gradient(135deg,#8fd4ff,#3ea8ff);
  --green:#34d399;--amber:#fbbf24;--red:#f87171;--blue:#8fd4ff;
  --r-lg:20px;--r-md:14px;--r-sm:11px;
  --shadow:0 24px 60px -24px rgba(0,0,0,.9);
  --font:"Outfit","Vazirmatn",system-ui,sans-serif;
}'''

EXTRA_CSS = r'''
/* ByteTunnel layout overhaul */
.layout{flex-direction:column}
.sidebar{width:100%;flex:0 0 auto;height:auto;position:sticky;top:0;flex-direction:row;align-items:center;border-inline-end:none;border-bottom:1px solid var(--border-soft);background:#000;z-index:50}
.sidebar .brand{padding:10px 16px}
.nav{flex-direction:row;padding:6px 8px;overflow-x:auto;gap:4px;flex:1;height:auto}
.nav-item{padding:8px 12px;white-space:nowrap;border-radius:999px}
.sidebar-foot{display:flex;flex-direction:row;border-top:none;padding:6px 12px;gap:4px}
.sidebar-foot .repo:first-child{display:none}
.stats-grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.stat-card{flex-direction:row;align-items:center;gap:14px;padding:14px 16px;background:#05080f;border-color:#1a335c}
.stat-card .sc-value{font-size:20px}
.dash-grid{grid-template-columns:1.35fr .85fr}
.card{background:#070b12;border-color:#1a335c}
table.users{min-width:0}
table.users thead{display:none}
table.users tbody{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px;padding:14px}
table.users tbody tr{display:flex;flex-direction:column;border:1px solid #1a335c;border-radius:16px;margin:0;padding:6px 0 8px;background:#05080f}
table.users td{display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px dashed #12243f;padding:8px 12px}
table.users td:last-child{border-bottom:none;justify-content:flex-end}
table.users td:before{content:attr(data-label);color:var(--faint);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.u-uuid{max-width:none}
.table-wrap{overflow:visible}
@media (max-width:900px){
  .stats-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .dash-grid{grid-template-columns:1fr}
  table.users tbody{grid-template-columns:1fr}
}
'''

def rebrand(html):
    html = html.replace(
        "family=Inter:wght@400;500;600;700;800&family=Vazirmatn:wght@400;500;600;700",
        "family=Outfit:wght@400;500;600;700;800&family=Vazirmatn:wght@400;500;600;700")
    html = html.replace('"Inter","Vazirmatn"', '"Outfit","Vazirmatn"')
    html = html.replace('"Vazirmatn","Inter"', '"Vazirmatn","Outfit"')
    html = html.replace("#22d3ee", "#8fd4ff")
    html = html.replace("#818cf8", "#3ea8ff")
    html = html.replace("rgba(34,211,238", "rgba(143,212,255")
    html = html.replace("rgba(129,140,248", "rgba(62,168,255")
    html = html.replace("Apex<small>PANEL</small>", "ByteTunnel<small>PANEL</small>")
    html = html.replace(">Apex<", ">ByteTunnel<")
    html = html.replace("Apex Panel", "ByteTunnel Panel")
    html = html.replace("Powered by Apex", "Powered by ByteTunnel")
    html = html.replace("t.me/NetraIR", "t.me/ByteTunnel")
    html = html.replace("@NetraIR", "@ByteTunnel")
    html = html.replace("NetraIR", "ByteTunnel")
    html = html.replace("https://github.com/netrair/Apex", "#")
    html = html.replace("github.com/netrair/Apex", "#")
    html = html.replace("Apex GitHub", "ByteTunnel")
    html = html.replace('alt="Apex"', 'alt="ByteTunnel"')
    html = html.replace("Apex is a lightweight", "ByteTunnel is a lightweight")
    html = html.replace("Apex یک پنل", "ByteTunnel یک پنل")
    html = re.sub(r"<title>.*?Apex.*?</title>", "<title>ByteTunnel Panel</title>", html)
    html = re.sub(r"(?<![a-zA-Z])Apex(?![a-zA-Z])", "ByteTunnel", html)
    return html

# LOGIN
m = re.search(r'("LOGIN_HTML_CONTENT":")([A-Za-z0-9+/=]+)(")', content)
login = gzip.decompress(base64.b64decode(m.group(2))).decode("utf-8", errors="replace")
login = re.sub(r"<style>.*?</style>", "<style>" + LOGIN_CSS + "</style>", login, count=1, flags=re.S)
login = login.replace("<body>\n<button", """<body>
<div class="shell">
<section class="hero">
  <div class="hero-kicker">BYTE TUNNEL</div>
  <h2>Control your<br>network in one place</h2>
  <p>Manage users, traffic and subscriptions from a fast Cloudflare panel.</p>
  <div class="hero-pills"><span>Workers</span><span>D1</span><span>Private panel</span></div>
</section>
<section class="form-side">
<button""")
login = login.replace("</div>\n<script>", "</div>\n</section>\n</div>\n<script>")
login = rebrand(login)
nb = base64.b64encode(gzip.compress(login.encode(), 9)).decode()
content = content[:m.start(2)] + nb + content[m.end(2):]
print("✓ صفحه ورود جدید")

# PANEL
m = re.search(r'("PANEL_HTML_CONTENT":")([A-Za-z0-9+/=]+)(")', content)
html = gzip.decompress(base64.b64decode(m.group(2))).decode("utf-8", errors="replace")
html = re.sub(r":root\{[^}]+\}", NEW_ROOT, html, count=1)
html = re.sub(r"body\{margin:0;background:[^;]+;", "body{margin:0;background:#000;", html, count=1)
html = html.replace("</style>\n</head>", EXTRA_CSS + "</style>\n</head>")
html = html.replace('data-label', 'data-label')  # noop
# add data-label on user cells if missing — CSS uses attr(data-label); original mobile css already expects it
html = rebrand(html)
nb = base64.b64encode(gzip.compress(html.encode(), 9)).decode()
content = content[:m.start(2)] + nb + content[m.end(2):]
print("✓ داشبورد و لیست کاربرها")

m2 = re.search(r'(APEX_LOGO\s*[:=]\s*")([^"]+)(")', content)
if m2:
    content = content[:m2.start(2)] + new_logo + content[m2.end(2):]
    print("✓ لوگو")

for old, new in [
    ('_project_:"Apex"', '_project_:"ByteTunnel"'),
    ('_project_SM_:"apex"', '_project_SM_:"bytetunnel"'),
    ("Apex Panel", "ByteTunnel Panel"),
    ("Apex Subscription", "ByteTunnel Subscription"),
    ("<b>Apex</b>", "<b>ByteTunnel</b>"),
    ("t.me/NetraIR", "t.me/ByteTunnel"),
    ("@NetraIR", "@ByteTunnel"),
    ("https://github.com/netrair/Apex", "#"),
    ("#22d3ee", "#8fd4ff"),
    ("#818cf8", "#3ea8ff"),
]:
    content = content.replace(old, new)

with open("worker.js", "w", encoding="utf-8") as f:
    f.write(content)
print("✓ فایل آماده")
PY

CREATE_DB=$(curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/d1/database" \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  --data "{\"name\":\"$DB_NAME\"}")
DB_ID=$(echo "$CREATE_DB" | jq -r '.result.uuid // .result.id // empty')
if [ -z "$DB_ID" ] || [ "$DB_ID" = "null" ]; then echo "$CREATE_DB" | jq .; exit 1; fi
echo "✓ DB $DB_ID"
SCHEMA=$(cat schema.sql | jq -Rs .)
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/d1/database/$DB_ID/query" \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  --data "{\"sql\":$SCHEMA}" > /dev/null

METADATA=$(jq -n --arg dbid "$DB_ID" '{
  "main_module": "worker.js",
  "bindings": [{"type": "d1", "name": "netra", "id": $dbid}],
  "compatibility_date": "2024-09-23",
  "compatibility_flags": ["nodejs_compat"]
}')
UPLOAD=$(curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME" \
  -H "Authorization: Bearer $API_TOKEN" \
  -F "metadata=$METADATA;type=application/json" \
  -F "worker.js=@worker.js;type=application/javascript+module")
if ! echo "$UPLOAD" | jq -e '.success == true' > /dev/null; then echo "$UPLOAD" | jq .; exit 1; fi

curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME/subdomain" \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  --data '{"enabled":true}' > /dev/null
SUBDOMAIN=$(curl -s -X GET "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/subdomain" \
  -H "Authorization: Bearer $API_TOKEN" | jq -r '.result.subdomain // empty')

if [ -z "$SUBDOMAIN" ] || [ "$SUBDOMAIN" = "null" ]; then
  echo "خطا: workers.dev subdomain برای این اکانت فعال نیست."
  echo "از Cloudflare Dashboard بخش Workers & Pages یک بار Workers را باز و فعال کنید."
  exit 1
fi

echo
echo "======================================"
echo "لینک پنل:"
echo "https://$WORKER_NAME.$SUBDOMAIN.workers.dev/apex/panel"
echo "======================================"
