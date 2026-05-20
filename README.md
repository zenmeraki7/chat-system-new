# ChatSystem — Multi-tenant AI Chat Platform

A SaaS platform where businesses register, get an embeddable chat widget, and OpenAI auto-replies to their website visitors.

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python FastAPI + SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Auth | JWT (python-jose) + bcrypt |
| Real-time | WebSockets (FastAPI native) |
| AI | OpenAI `gpt-4o-mini` |
| Frontend | Next.js 15 + Tailwind CSS |
| DevOps | Docker + Docker Compose |

---

## Quick Start (Docker)

```bash
# 1. Fill in your OpenAI key
cp backend/.env.example backend/.env
# Edit backend/.env and set OPENAI_API_KEY=sk-...

# 2. Start everything
docker-compose up --build

# API docs: http://localhost:8000/docs
# Dashboard: http://localhost:3000
```

---

## Local Development (without Docker)

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
# Set up local PostgreSQL and update DATABASE_URL in .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

---

## Architecture

```
Business registers → gets JWT token
Business dashboard → copies widget <script> tag
Embed on website → widget.js loads in visitor's browser
Visitor opens chat → WebSocket connects to /ws/chat/{api_key}/{visitor_id}
Visitor sends message → saved to DB, sent to OpenAI, AI reply saved + returned
Visitor returns → message history restored from DB via visitor_id (localStorage)
```

---

## API Endpoints

### Auth
| Method | Endpoint | Auth |
|--------|----------|------|
| POST | `/api/v1/auth/register` | Public |
| POST | `/api/v1/auth/login` | Public |
| GET | `/api/v1/auth/me` | JWT |

### Business Dashboard
| Method | Endpoint | Auth |
|--------|----------|------|
| GET/PATCH | `/api/v1/business/me` | JWT |
| GET | `/api/v1/business/widget-script` | JWT |
| POST | `/api/v1/business/regenerate-key` | JWT |
| GET | `/api/v1/conversations` | JWT |
| GET | `/api/v1/conversations/{id}/messages` | JWT |

### Widget (Public)
| Method | Endpoint | Auth |
|--------|----------|------|
| POST | `/api/v1/public/conversations/start` | API Key |
| GET | `/api/v1/public/conversations/history` | API Key |
| WS | `/ws/chat/{api_key}/{visitor_id}` | API Key |

---

## Widget Embedding

After registering, copy the script from your dashboard Settings page and paste before `</body>`:

```html
<!-- ChatSystem Widget -->
<script>
  window.ChatWidgetConfig = {
    apiKey: "YOUR-API-KEY",
    baseUrl: "https://your-api.com",
    primaryColor: "#6366f1",
    title: "Chat with us"
  };
</script>
<script src="https://your-api.com/widget.js" async defer></script>
```
