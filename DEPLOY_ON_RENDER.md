# 🚀 Deploy JARVIS to Render.com (100% Free 24/7 Guide)

Is guide ki madad se aap apne phone ke liye JARVIS ko **Render Cloud** par 24/7 bina kisi laptop ke chala sakte hain.

---

## Step 1: Render.com par Login karein
1. [https://render.com](https://render.com) par jayein.
2. Apne **GitHub account** se Free Sign Up / Log In karein.

---

## Step 2: New Web Service banayein
1. Dashboard me top-right par **"New +"** button dabayein.
2. **"Web Service"** select karein.
3. List me se **`jarvis_render_version`** repository choose karein (Connect dabayein).

---

## Step 3: Deployment Settings bharein

Render par yeh settings set karein:

* **Name:** `jarvis-assistant` (ya koi bhi manpasand naam)
* **Region:** `Oregon (US West)` ya `Singapore`
* **Branch:** `main`
* **Runtime:** `Python 3`
* **Build Command:**
  ```bash
  pip install -r requirements-render.txt
  ```
* **Start Command:**
  ```bash
  python render_server.py
  ```
* **Instance Type:** **Free** ($0 / month)

---

## Step 4: Gemini API Key daalein (Zaroori)
1. Page ke neeche **"Environment Variables"** section me jayein.
2. **"Add Environment Variable"** par click karein:
   * **Key:** `GEMINI_API_KEY`
   * **Value:** *(Apni Google Gemini API Key paste karein)*

---

## Step 5: Deploy karein!
1. Page ke end me **"Create Web Service"** / **"Deploy Web Service"** par click karein.
2. Render build start karega aur 1-2 minute me deploy ho jayega.
3. Aapko ek live public link mil jayega, jaise:
   `https://jarvis-assistant-xxxx.onrender.com`

---

## Step 6: Phone par App kholein aur Install karein
1. Phone ke Chrome ya Brave browser me yeh link kholein:
   ```text
   https://YOUR-APP-NAME.onrender.com/auto-login?key=0000
   ```
2. Browser ke top-right **3 dots (⋮)** par tap karein aur **"Install app"** / **"Add to Home screen"** dabayein.
3. Ab aapka JARVIS 24/7 aapke phone par chalega, chahe aapka laptop band ho ya toot jaye!
