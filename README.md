# Clothing Inventory App

A simple local-first clothing inventory web app built with Python, FastAPI, SQLite, and Docker.

## Goals
- Track owned clothing items locally
- Store item details in a database
- Save simple item images to local storage
- Run on a home network at a local IP address via Docker

## Architecture
- Backend: FastAPI
- Database: SQLite
- File storage: local filesystem under uploads/
- Container: Docker Compose

## Run locally

### With Docker
```bash
docker compose up --build
```

Then open http://localhost:8000 or http://<your-local-ip>:8000 from another device on your home network.

### Local development
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Project roadmap
- Frontend polish: improve forms, responsive layout, and clearer item cards.
- Backend stability: add structured migrations and stronger validation.
- Security: harden sessions, admin checks, and password handling.
- DevOps: GitHub Actions CI, Docker improvements, and backup strategy.
- Accessibility and docs: keyboard-friendly flows and contributor guidance.

## Suggested next steps

### Phase 1: Core usability
- Add a clearer dashboard showing the current user and item count
- Support editing and deleting clothing items
- Improve the form layout and add basic validation
- Show a friendly empty state when no items exist

### Phase 2: Better inventory organization
- Add search and filtering by category, color, size, and name
- Support tags such as casual, formal, seasonal, or favorite
- Add basic sorting options like newest, oldest, or alphabetical

### Phase 3: Wear and outfit tracking
- Track how often each item is worn
- Add a simple wear-history log
- Let users mark items as favorite or wishlist items

### Phase 4: Better media and sharing
- Add image thumbnails and better upload handling
- Support multiple images per clothing item
- Allow simple export/import of the inventory data

### Phase 5: Home-network polish
- Add a lightweight mobile-friendly UI
- Add HTTPS support via a reverse proxy if you want remote access later
- Consider a more robust database such as PostgreSQL if the app grows

## License
This project is released under the GNU General Public License v3.0 (GPL-3.0-or-later).
A `LICENSE` file is present in the repository.

Dependency compatibility note: the project's direct Python dependencies listed in `requirements.txt` (FastAPI, Uvicorn, SQLAlchemy, python-multipart, pytest, httpx) are permissively licensed (MIT/BSD) and are generally compatible with GPL-3.0. If you add new dependencies, verify their licenses before including them in a GPL-licensed project.
