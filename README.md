# Url_and_content_filtering agent installation 

# 📘 MITMPROXY INSTALLATION & CONFIGURATION GUIDE (WINDOWS)

**Objective:** Install mitmproxy on Windows, configure system proxy, install trusted certificate, and verify that all browser traffic is intercepted successfully.

---

## 🔗 Official Resources

- 🌐 **Official Website**: [https://mitmproxy.org](https://mitmproxy.org)
- 📦 **Windows Download Page**: [https://mitmproxy.org/downloads/](https://mitmproxy.org/downloads/)
- 📚 **Official Documentation**: [https://docs.mitmproxy.org/stable/](https://docs.mitmproxy.org/stable/)
- 🔐 **Certificate Documentation**: [https://docs.mitmproxy.org/stable/concepts-certificates/](https://docs.mitmproxy.org/stable/concepts-certificates/)

---

## ✅ SYSTEM REQUIREMENTS

- Windows 10 / 11 (64-bit)
- Administrator privileges
- Google Chrome / Edge
- Internet access

---

## 🧩 STEP 1 — Download & Install mitmproxy

1. Open browser and go to: [https://mitmproxy.org/downloads/](https://mitmproxy.org/downloads/)
2. Download: `mitmproxy-windows-x86_64-installer.exe`
3. Run the installer:
   - Accept license
   - Install with default options
   - Finish installation
4. Verify installation:
   - Open Command Prompt and run:
     ```bash
     mitmweb --version
     ```
   - **Expected output:** `mitmproxy X.Y.Z`

---

## 🧩 STEP 2 — Start mitmproxy Web Interface

1. Open Command Prompt / PowerShell
2. Run:
   ```bash
   mitmproxy --listen-port 8082 -s .\agent.py
   ```
3. You should see:
   ```
   HTTP(S) proxy listening at *:8080
   Web server listening at http://127.0.0.1:8081
   ```

⚠️ **Keep this terminal open.**

---

## 🧩 STEP 3 — Configure Windows Proxy Settings

1. Open: **Settings → Network & Internet → Proxy**
2. **Disable:**
   - Automatically detect settings → **OFF**
   - Setup script → **OFF**
3. **Enable:**
   - Use a proxy server → **ON**
   - Address → `127.0.0.1`
   - Port → `8080`
4. Click **Save**

---

## 🧩 STEP 4 — Verify Proxy Routing

1. Close all browser windows.
2. Reopen browser.
3. Open: [http://mitm.it](http://mitm.it)

✅ **Expected:** mitmproxy certificate download page should appear.

If not working, test manually:
```bash
curl -v -x http://127.0.0.1:8080 http://mitm.it
```

---

## 🧩 STEP 5 — Download Correct Certificate

From the [mitm.it](http://mitm.it) page:

1. Click: **Windows**
2. Download file: `mitmproxy-ca-cert.cer`

⚠️ **Do NOT download .p12 or .pfx.**

---

## 🧩 STEP 6 — Install Certificate (Trusted Root)

1. Double-click the downloaded `.cer` file.
2. Click: **Install Certificate**
3. Select: **Local Machine**
4. Click: **Place all certificates in the following store**
5. Browse → Select: **Trusted Root Certification Authorities**
6. Finish installation.

**Expected message:** *The import was successful.*

---

## 🧩 STEP 7 — Restart Browser & Verify HTTPS Capture

1. Close browser completely.
2. Open browser again.
3. Open: [https://google.com](https://google.com)
4. Open mitm UI: [http://127.0.0.1:8081/#/flows](http://127.0.0.1:8081/#/flows)

✅ **You should see HTTPS traffic flowing.**

---

## 🧩 STEP 8 — Validation Checklist

| Test | Expected Result |
|------|----------------|
| `mitmweb` running | Port 8080 listening |
| mitm.it opens | Certificate page visible |
| HTTPS browsing | No SSL errors |
| mitm UI flows | Requests visible |
| curl proxy test | HTTP 200 |

---

## 🧩 STEP 9 — Common Problems & Fixes

### ❌ mitm.it not opening
✔ Check proxy port is 8080, not 8081  
✔ Restart browser  
✔ Disable VPN  
✔ Force Chrome proxy:
```bash
chrome.exe --proxy-server="127.0.0.1:8080"
```

### ❌ Certificate asks for password
✔ Wrong file downloaded  
✔ Download `.cer` only from Windows button

### ❌ HTTPS shows SSL errors
✔ Certificate not installed in Trusted Root  
✔ Restart browser

### ❌ No flows in UI
✔ System proxy not applied  
✔ Use forced Chrome proxy

---

## 🧩 STEP 10 — Stop mitmproxy & Restore Network

When finished:

1. Turn **OFF** proxy in Windows settings.
2. Close mitmproxy terminal.

---

**Guide complete! You should now have mitmproxy fully operational on Windows.**
