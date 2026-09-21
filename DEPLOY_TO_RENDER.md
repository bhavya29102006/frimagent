# 🚀 Deploying FirmAgent to Render (render.com)

This step-by-step guide walks you through deploying FirmAgent to **Render** as a live, publicly accessible web application in under 3 minutes.

---

## ⚡ Quick Method: Deploy via GitHub (Recommended)

### Step 1: Push your latest code to GitHub
Make sure all files, including `render.yaml` and `.streamlit/config.toml`, are committed and pushed to your GitHub repository:
```bash
git add .
git commit -m "Configure project for Render deployment"
git push origin main
```

---

### Step 2: Create a New Web Service on Render
1. Go to [dashboard.render.com](https://dashboard.render.com) and log in (or sign up with GitHub).
2. In the top right corner, click **New +** and select **Web Service**.
3. Choose **Build and deploy from a Git repository** and click **Next**.
4. Connect your GitHub account and select your **`firmagent`** repository.

---

### Step 3: Configure Service Settings
Fill in the following fields:

| Field | Value |
| :--- | :--- |
| **Name** | `firmagent` *(or any name you prefer)* |
| **Region** | Choose the closest region (e.g., *Oregon (US West)* or *Frankfurt (EU)*) |
| **Branch** | `main` |
| **Runtime** | **Python 3** *(or Docker if you prefer)* |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `streamlit run app/main.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` |
| **Instance Type** | **Free** ($0/month) |

---

### Step 4: Add Environment Variables
Scroll down to the **Environment Variables** section and click **Add Environment Variable**:

1. **`GEMINI_API_KEY`**: Paste your Google Gemini API key (from [ai.google.dev](https://aistudio.google.com/)).
2. **`PYTHON_VERSION`**: `3.11.9`
3. *(Optional)* **`WOKWI_CLI_TOKEN`**: Your Wokwi CI token (if using Wokwi cloud simulation).

> 💡 **Tip**: Even without `WOKWI_CLI_TOKEN`, FirmAgent works 100% offline out-of-the-box using the built-in **Universal Virtual Hardware Simulator**!

---

### Step 5: Deploy!
1. Click **Create Web Service** (or **Deploy**).
2. Render will pull your repository, install Python dependencies, and start Streamlit.
3. Once the deploy finishes (takes ~1-2 minutes), Render will display your live public URL:
   ```text
   https://firmagent.onrender.com
   ```

---

## 🛠️ Alternative Method: 1-Click Blueprint (`render.yaml`)

Because this repository already contains a pre-configured [`render.yaml`](file:///c:/Users/bhavy/Downloads/firmagent-kit/firmagent/render.yaml), you can also deploy using Render Blueprints:

1. Go to [dashboard.render.com](https://dashboard.render.com).
2. Click **New +** ➔ **Blueprint**.
3. Connect your Git repository.
4. Render will read `render.yaml` and configure all settings automatically.
5. Provide your `GEMINI_API_KEY` when prompted and click **Apply**.

---

## 🐳 Alternative Method: Containerized Docker Deployment

If you prefer deploying with full control over the Linux build toolchains (GCC, G++, Make):

1. Follow **Step 2** above.
2. Under **Runtime**, select **Docker** instead of Python.
3. Render will automatically detect the included [`Dockerfile`](file:///c:/Users/bhavy/Downloads/firmagent-kit/firmagent/Dockerfile).
4. Add your `GEMINI_API_KEY` environment variable and deploy!

---

## 💡 Important Render Free-Tier Notes

1. **Auto-Sleep**: On the Render Free tier, web services spin down after 15 minutes of inactivity. The first request after sleep takes ~30-50 seconds to wake up (subsequent requests are instant).
2. **Memory Limit**: Render Free offers **512 MB RAM**. FirmAgent runs at **~120 MB RAM**, easily staying well within the free tier limits.
3. **Persistent Data**: Render Free web services have ephemeral disks. FirmAgent's built-in SQLite database (`runs/firmagent.db`) and firmware cache persist in memory during active runs.
