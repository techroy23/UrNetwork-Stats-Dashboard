# UR Transfer Stats Dashboard

A lightweight Flask dashboard to track your BringYour.io bandwidth usage.  
It logs your paid/unpaid bytes every 15 minutes (or on-demand), stores them in SQLite, and presents a responsive Bootstrap table with:

- Automatic 15-minute polling via APScheduler  
- Manual “Fetch Now” button  
- “Clear DB” reset with confirmation  
- Real-time countdown & spinner on auto-fetch  
- Light/dark theme toggle (persists via URL param)  
- Local‐time date-time display  
- Δ Unpaid Bytes & Δ Unpaid GB columns  

---

## 🔥 Features

1. **Scheduler:** Logs transfer stats at `:00`, `:15`, `:30`, `:45` automatically.  
2. **Manual Control:** Instantly fetch fresh stats with a button and spinner feedback.  
3. **Persistence:** SQLite backend; `.env` storage for JWT with safe updates.  
4. **UI:**  
   - Bootstrap 5.3 styling  
   - Light/dark mode toggle  
   - Sticky header with next-fetch & live countdown  
5. **Deltas:** Computes per‐interval changes in both bytes and gigabytes.  

---

## ⚙️ Usage
- Toggle Theme: Switch light/dark mode.
- Fetch Now: Manually pull stats spinner animation provided.
- Clear DB: Red button wipes all records with confirmation.
- Automatic Logging: In background 15 minute schedule.

---

## 🚀 Getting Started

### Prerequisites
```
Docker
```

### Build and Run

```bash
git clone https://github.com/techroy23/UrNetwork-Stats-Dashboard
cd UrNetwork-Stats-Dashboard
cp .env.example .env
# then edit .env and set UR_USER and UR_PASS or UR_JWT

docker build -t urnetwork-stats-dashboard .

docker run -d \
  --env-file .env \
  -p 3000:3000 \
  --name urnetwork-stats-dashboard \
  urnetwork-stats-dashboard
```
