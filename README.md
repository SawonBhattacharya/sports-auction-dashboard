# Real-Time Sports Auction Portal

Streamlit application for running a real-time sports/cricket auction. It supports dual-mode operation: running locally with a lightweight SQLite database (`auction.db`) or deployed to Streamlit Community Cloud with a cloud-hosted Supabase PostgreSQL database.

## 🚀 Deployment Stack

- **Frontend/Control**: [Streamlit Community Cloud](https://streamlit.io/cloud) (deploys directly from GitHub)
- **Database**: [Supabase PostgreSQL](https://supabase.com) (generous free-tier managed Postgres)

---

## 🛠️ Local Development & Quick Start (SQLite Fallback)

To run the app locally without setting up a cloud database:

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Local Passcodes**:
   Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and set your passcodes:
   ```toml
   [passcodes]
   admin = "admin123"
   viewer = "viewer"
   ```
   *Note: If the `[database]` configuration is omitted or commented out, the app automatically falls back to local SQLite mode.*

3. **Run Streamlit**:
   ```bash
   streamlit run app.py
   ```

---

## 🌐 Production Deployment (Supabase + Streamlit Cloud)

### 1. Set Up Supabase Database
1. Create a free account at [Supabase](https://supabase.com).
2. Create a new project. Choose a database password and select a region close to your users.
3. Once the database is ready, go to **Settings → Database** and scroll to **Connection string**.
4. Select the **URI** tab, choose **Mode: Transaction** (Connection Pooler on port `6543`), and copy the connection string. Replace `[YOUR-PASSWORD]` with your actual database password.

### 2. Initialize the Database Schema (Optional but Recommended)
You can let the app automatically initialize tables on its first run, or you can manually bootstrap them:
1. Copy the contents of [schema.sql](file:///c:/Users/PC/Desktop/auction-dashboard/schema.sql).
2. In Supabase, go to the **SQL Editor** in the left sidebar.
3. Click **New Query**, paste the schema SQL, and click **Run**. This will create the required tables and seed the default teams.

### 3. Deploy to Streamlit Community Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account.
2. Click **New app**, select your repository, branch (e.g., `legacy`), and set the main file path to `app.py`.
3. Click **Advanced settings...** before deploying.
4. Under **Secrets**, paste the contents of your configured `.streamlit/secrets.toml` including the database URL:
   ```toml
   [database]
   url = "postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres"

   [passcodes]
   admin = "your-strong-admin-passcode"
   viewer = "your-viewer-passcode"
   ```
5. Click **Save** and then click **Deploy**!

---

## 📂 Git & Repository Hygiene

Sensitive files, logs, and virtual environments should **never** be committed to version control. The repository is configured with a `.gitignore` file that excludes:
- Local SQLite database files (`*.db`)
- Python virtual environments (`.venv/`)
- Compiled python bytecode (`__pycache__/`)
- Local secrets configuration (`.streamlit/secrets.toml`)
- Application logs (`*.log`)

To ensure clean deployments, all previously tracked runtime files have been removed from the Git index (without deleting them locally) using:
```bash
git rm -r --cached .venv __pycache__ auction.db *.log
```

---

## 🏏 Player & Team Management

- **Team Configuration**: Default teams are seeded automatically. You can modify them directly in the database or update the seed values in [schema.sql](file:///c:/Users/PC/Desktop/auction-dashboard/schema.sql) / `init_db()` in `app.py`.
- **Player Sync**: The Admin Panel includes an option to sync player data from `Auction Tracker v3.xlsx`. If you update the Excel sheet and push the changes to GitHub, the Admin can click **Sync Players** in the admin panel of the deployed app to refresh/re-import all player details into your cloud database.
- **Player Photos**: Player photos are loaded from the `images/player_photo` directory. Ensure any new player photo names match their names in the Excel sheet exactly and are committed to the repository.
