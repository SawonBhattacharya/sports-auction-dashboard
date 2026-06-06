# Real-Time Sports Auction Portal

Streamlit app for running a local cricket/sports auction from `Auction Tracker v3.xlsx`.

## Run

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Default passcodes:

- Admin: `admin123`
- Viewer: `viewer`

You can override them with environment variables:

```powershell
$env:AUCTION_ADMIN_PASSCODE="your-admin-code"
$env:AUCTION_VIEWER_PASSCODE="your-viewer-code"
streamlit run app.py
```

## What It Includes

- Role-based admin/viewer login.
- SQLite-backed shared auction state in `auction.db`.
- Excel import from the `Player_DB` sheet, enriched from registration responses when names match.
- Admin random player draw, sold/unsold actions, bid validation, and correction panel.
- Viewer live stage with automatic 2-second refresh.
- Team purse, squad count, max bid power, highest bid, unsold count, and audit logs.

The generated `auction.db` file is runtime state and can be deleted to restart from a clean auction.
