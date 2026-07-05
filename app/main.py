from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from pathlib import Path
import hashlib
import hmac
import os
import secrets
import shutil
import uuid

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'inventory.db'}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

SESSION_COOKIE_NAME = "inventory_session"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
CATEGORY_OPTIONS = ["Top", "Bottom", "Dress", "Outerwear", "Shoes", "Accessories", "Other"]
SIZE_OPTIONS = ["XS", "S", "M", "L", "XL", "XXL", "One Size"]
PANT_WAIST_OPTIONS = list(range(28, 41))
PANT_LENGTH_OPTIONS = list(range(30, 37))
SHOE_SIZES = [str(s) for s in range(6, 14)]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    session_token = Column(String, nullable=True)


class ClothingItem(Base):
    __tablename__ = "clothing_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    color = Column(String, nullable=False)
    size = Column(String, nullable=False)
    tags = Column(String, nullable=True)
    size_type = Column(String, nullable=False, default="tshirt")
    pant_waist = Column(Integer, nullable=True)
    pant_length = Column(Integer, nullable=True)
    shoe_size = Column(String, nullable=True)
    favorite = Column(Integer, nullable=False, default=0)
    archived = Column(Integer, nullable=False, default=0)
    image_filename = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)


class OutfitTemplate(Base):
    __tablename__ = "outfit_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    tags = Column(String, nullable=False)
    item_ids = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000).hex()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt, hashed = stored_hash.split(":", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000).hex()
    return hmac.compare_digest(check, hashed)


def ensure_admin_user() -> None:
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not admin:
            admin = User(username=ADMIN_USERNAME, password_hash=hash_password(ADMIN_PASSWORD))
            db.add(admin)
            db.commit()
            db.refresh(admin)
    finally:
        db.close()


def migrate_schema() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "clothing_items" in inspector.get_table_names():
        clothing_columns = {column["name"] for column in inspector.get_columns("clothing_items")}
        if "user_id" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN user_id INTEGER"))

            db = SessionLocal()
            try:
                default_user = db.query(User).filter(User.username == "default").first()
                if not default_user:
                    default_user = User(username="default", password_hash=hash_password("changeme"))
                    db.add(default_user)
                    db.commit()
                    db.refresh(default_user)

                db.execute(text("UPDATE clothing_items SET user_id = :user_id WHERE user_id IS NULL"), {"user_id": default_user.id})
                db.commit()
            finally:
                db.close()

    if "clothing_items" in inspector.get_table_names():
        clothing_columns = {column["name"] for column in inspector.get_columns("clothing_items")}
        if "tags" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN tags VARCHAR"))

        if "favorite" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN favorite INTEGER DEFAULT 0 NOT NULL"))

        if "archived" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN archived INTEGER DEFAULT 0 NOT NULL"))
        if "size_type" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN size_type VARCHAR DEFAULT 'tshirt' NOT NULL"))

        if "pant_waist" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN pant_waist INTEGER"))

        if "pant_length" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN pant_length INTEGER"))

        if "shoe_size" not in clothing_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE clothing_items ADD COLUMN shoe_size VARCHAR"))


migrate_schema()
ensure_admin_user()

app = FastAPI(title="Clothing Inventory")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


def get_authenticated_user(request: Request, db):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="login required")

    user = db.query(User).filter(User.session_token == session_token).first()
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in {401, 403}:
        return HTMLResponse(content=render_page(request, error_message="Admin access is required. Please log in as an admin." if exc.status_code == 403 else "Please log in to continue."), status_code=exc.status_code)
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


def is_admin_user(user: User | None) -> bool:
    return user is not None and user.username == ADMIN_USERNAME


def render_page(request: Request, user: User | None = None, error_message: str | None = None, success_message: str | None = None, tag_filter: str | None = None):
    db = SessionLocal()
    try:
        if user is None:
            session_token = request.cookies.get(SESSION_COOKIE_NAME)
            user = db.query(User).filter(User.session_token == session_token).first() if session_token else None

        if user:
            items_query = db.query(ClothingItem).filter(ClothingItem.user_id == user.id)
            if tag_filter:
                tag_filter = tag_filter.strip().lower()
                items_query = items_query.filter(ClothingItem.tags.ilike(f"%{tag_filter}%"))
            items = items_query.order_by(ClothingItem.id.desc()).all()
            item_lines = []
            for item in items:
                if item.size_type == 'pants' and item.pant_waist and item.pant_length:
                    display_size = f"{item.pant_waist}x{item.pant_length}"
                elif item.size_type == 'shoes' and item.shoe_size:
                    display_size = str(item.shoe_size)
                else:
                    display_size = item.size or ""

                tag_html = f" — Tags: {item.tags}" if item.tags else ""
                image_html = f" — <a href=\"/uploads/{item.image_filename}\" target=\"_blank\">image</a>" if item.image_filename else ""
                fav_html = " — Favorite" if item.favorite else ""
                arch_html = " — Archived" if item.archived else ""
                actions = (
                    f" <form action='/items/{item.id}/favorite' method='post' style='display:inline'><button type='submit'>{'Unfavorite' if item.favorite else 'Favorite'}</button></form>"
                    f" <form action='/items/{item.id}/archive' method='post' style='display:inline'><button type='submit'>{'Unarchive' if item.archived else 'Archive'}</button></form>"
                    f" <form action='/items/{item.id}/delete' method='post' style='display:inline'><button type='submit' onclick=\"return confirm('Delete this item?')\">Delete</button></form>"
                    f" <form action='/items/{item.id}/update' method='get' style='display:inline'><button type='submit'>Edit</button></form>"
                )
                item_lines.append(f"<li><strong>{item.name}</strong> — {item.category} — {item.color} — {display_size}{tag_html}{image_html}{fav_html}{arch_html}{actions}</li>")
            item_html = "".join(item_lines)
            empty_state = "<li>No items yet.</li>" if not items else ""
            admin_link = "<p><a href='/admin'>Open admin portal</a></p>" if is_admin_user(user) else ""
            templates = db.query(OutfitTemplate).filter(OutfitTemplate.user_id == user.id).order_by(OutfitTemplate.id.desc()).all()
            template_html = "".join(
                f"<li><strong>{template.name}</strong> — tags: {template.tags} — items: {template.item_ids}</li>"
                for template in templates
            )
            template_state = "<li>No outfit templates yet.</li>" if not templates else ""
            alert = ""
            if error_message:
                alert = f"<p style='padding:0.75rem;border:1px solid #b91c1c;background:#fee2e2;color:#991b1b;border-radius:6px'>{error_message}</p>"
            if success_message:
                alert = f"<p style='padding:0.75rem;border:1px solid #15803d;background:#dcfce7;color:#166534;border-radius:6px'>{success_message}</p>"
            return f"""
            <html>
              <head><title>Clothing Inventory</title></head>
              <body style='font-family: sans-serif; max-width: 700px; margin: 2rem auto;'>
                <h1>Clothing Inventory</h1>
                <p>Logged in as {user.username}</p>
                {admin_link}
                {alert}
                <form action='/logout' method='post'>
                  <button type='submit'>Log out</button>
                </form>
                <hr>
                <h2>Add Item</h2>
                <form action='/items' method='post' enctype='multipart/form-data'>
                  <p><label>Name: <input name='name' required></label></p>
                  <p><label>Category:
                    <select name='category' required>
                      <option value=''>Select a category</option>
                      {''.join(f"<option value='{option}'>{option}</option>" for option in CATEGORY_OPTIONS)}
                    </select>
                  </label></p>
                  <p><label>Color: <input name='color' required></label></p>
                                    <p><label>Size Type:
                                        <select name='size_type' id='size_type' required>
                                            <option value='tshirt'>T-Shirt</option>
                                            <option value='pants'>Pants (waist x length)</option>
                                            <option value='shoes'>Shoes</option>
                                            <option value='other'>Other</option>
                                        </select>
                                    </label></p>

                                    <div id='tshirt_size'>
                                    <p><label>Size:
                                        <select name='size'>
                                            <option value=''>Select a size</option>
                                            {''.join(f"<option value='{option}'>{option}</option>" for option in SIZE_OPTIONS)}
                                        </select>
                                    </label></p>
                                    </div>

                                    <div id='pants_size' style='display:none'>
                                        <p><label>Waist:
                                            <select name='pant_waist'>
                                                <option value=''>Waist</option>
                                                {''.join(f"<option value='{w}'>{w}</option>" for w in PANT_WAIST_OPTIONS)}
                                            </select>
                                        </label></p>
                                        <p><label>Length:
                                            <select name='pant_length'>
                                                <option value=''>Length</option>
                                                {''.join(f"<option value='{l}'>{l}</option>" for l in PANT_LENGTH_OPTIONS)}
                                            </select>
                                        </label></p>
                                    </div>

                                    <div id='shoe_size' style='display:none'>
                                        <p><label>Shoe size: <input name='shoe_size' list='shoe_sizes'></label></p>
                                        <datalist id='shoe_sizes'>{''.join(f"<option value='{s}'>" for s in SHOE_SIZES)}</datalist>
                                    </div>

                                    <p><label>Tags: <input name='tags' placeholder='casual, work, weekend'></label></p>
                                    <p><label>Image: <input type='file' name='image'></label></p>
                                    <button type='submit'>Save Item</button>

                                    <script>
                                        (function(){{
                                            var sizeType = document.getElementById('size_type');
                                            var tshirt = document.getElementById('tshirt_size');
                                            var pants = document.getElementById('pants_size');
                                            var shoe = document.getElementById('shoe_size');
                                            function update(){{
                                                var v = sizeType.value;
                                                tshirt.style.display = v === 'tshirt' || v === 'other' ? '' : 'none';
                                                pants.style.display = v === 'pants' ? '' : 'none';
                                                shoe.style.display = v === 'shoes' ? '' : 'none';
                                            }}
                                            sizeType.addEventListener('change', update);
                                            update();
                                        }})();
                                    </script>
                </form>
                <hr>
                <h2>Filter Inventory</h2>
                <form action='/' method='get'>
                  <p><label>Tag: <input name='tag' value='{tag_filter or ""}'></label></p>
                  <button type='submit'>Filter</button>
                </form>
                <hr>
                <h2>Your Inventory</h2>
                <ul>{item_html}{empty_state}</ul>
                <hr>
                <h2>Outfit Templates</h2>
                <form action='/outfits' method='post'>
                  <p><label>Name: <input name='name' required></label></p>
                  <p><label>Tags: <input name='tags' placeholder='work, casual'></label></p>
                  <button type='submit'>Save Template</button>
                </form>
                <ul>{template_html}{template_state}</ul>
              </body>
            </html>
            """

        alert = ""
        if error_message:
            alert = f"<p style='padding:0.75rem;border:1px solid #b91c1c;background:#fee2e2;color:#991b1b;border-radius:6px'>{error_message}</p>"
        if success_message:
            alert = f"<p style='padding:0.75rem;border:1px solid #15803d;background:#dcfce7;color:#166534;border-radius:6px'>{success_message}</p>"
        return f"""
        <html>
          <head><title>Clothing Inventory</title></head>
          <body style='font-family: sans-serif; max-width: 700px; margin: 2rem auto;'>
            <h1>Clothing Inventory</h1>
            {alert}
            <p>Please sign up or log in to manage your inventory.</p>
            <h2>Sign up</h2>
            <form action='/signup' method='post'>
              <p><label>Username: <input name='username' required></label></p>
              <p><label>Password: <input type='password' name='password' required></label></p>
              <button type='submit'>Sign up</button>
            </form>
            <h2>Log in</h2>
            <form action='/login' method='post'>
              <p><label>Username: <input name='username' required></label></p>
              <p><label>Password: <input type='password' name='password' required></label></p>
              <button type='submit'>Log in</button>
            </form>
          </body>
        </html>
        """
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    tag_filter = request.query_params.get("tag")
    return render_page(request, tag_filter=tag_filter)


@app.post("/signup")
def signup(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return render_page(request, error_message="That username is already taken. Please try another.")

        user = User(username=username, password_hash=hash_password(password), session_token=secrets.token_urlsafe(24))
        db.add(user)
        db.commit()
        db.refresh(user)

        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key=SESSION_COOKIE_NAME, value=user.session_token, httponly=True, samesite="lax")
        return response
    finally:
        db.close()


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            return render_page(request, error_message="Invalid username or password. Please try again.")

        user.session_token = secrets.token_urlsafe(24)
        db.commit()

        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key=SESSION_COOKIE_NAME, value=user.session_token, httponly=True, samesite="lax")
        return response
    finally:
        db.close()


@app.post("/logout")
def logout(request: Request):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.session_token == session_token).first()
            if user:
                user.session_token = None
                db.commit()
        finally:
            db.close()

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.post("/items")
def create_item(request: Request, name: str = Form(...), category: str = Form(...), color: str = Form(...), size_type: str = Form('tshirt'), size: str = Form(''), pant_waist: int | None = Form(None), pant_length: int | None = Form(None), shoe_size: str = Form(''), tags: str = Form(""), image: UploadFile | None = File(None)):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before adding items.")

        filename = None
        if image and image.filename:
            safe_name = Path(image.filename).name
            filename = f"{user.id}_{uuid.uuid4().hex}_{safe_name}"
            destination = UPLOAD_DIR / filename
            with destination.open("wb") as buffer:
                shutil.copyfileobj(image.file, buffer)

        normalized_tags = ", ".join(tag.strip() for tag in tags.split(",") if tag.strip())
        # determine stored size depending on size_type
        stored_size = size
        p_waist = None
        p_length = None
        s_size = None
        if size_type == 'pants':
            p_waist = pant_waist
            p_length = pant_length
            if p_waist and p_length:
                stored_size = f"{p_waist}x{p_length}"
        elif size_type == 'shoes':
            s_size = shoe_size
            stored_size = s_size

        item = ClothingItem(name=name, category=category, color=color, size=stored_size or "", tags=normalized_tags, size_type=size_type, pant_waist=p_waist, pant_length=p_length, shoe_size=s_size, image_filename=filename, user_id=user.id)
        db.add(item)
        db.commit()
        db.refresh(item)
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/outfits")
def create_outfit_template(request: Request, name: str = Form(...), tags: str = Form("")):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before saving outfit templates.")

        matching_items = db.query(ClothingItem).filter(ClothingItem.user_id == user.id).all()
        matching_ids = []
        for item in matching_items:
            item_tags = [tag.strip().lower() for tag in (item.tags or "").split(",") if tag.strip()]
            requested_tags = [tag.strip().lower() for tag in tags.split(",") if tag.strip()]
            if any(tag in item_tags for tag in requested_tags):
                matching_ids.append(str(item.id))

        template = OutfitTemplate(name=name, tags=tags, item_ids=",".join(matching_ids), user_id=user.id)
        db.add(template)
        db.commit()
        db.refresh(template)
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.get("/items/{item_id}/update", response_class=HTMLResponse)
def edit_item_page(request: Request, item_id: int):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before editing items.")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id, ClothingItem.user_id == user.id).first()
        if not item:
            return render_page(request, user=user, error_message="Item not found.")

        return f"""
        <html>
          <head><title>Edit Item</title></head>
          <body style='font-family: sans-serif; max-width: 700px; margin: 2rem auto;'>
            <h1>Edit Item</h1>
            <p><a href='/'>Back to inventory</a></p>
            <form action='/items/{item.id}/update' method='post' enctype='multipart/form-data'>
              <p><label>Name: <input name='name' value='{item.name}' required></label></p>
              <p><label>Category:
                <select name='category' required>
                  <option value=''>Select a category</option>
                  {''.join(f"<option value='{option}'{' selected' if option == item.category else ''}>{option}</option>" for option in CATEGORY_OPTIONS)}
                </select>
              </label></p>
              <p><label>Color: <input name='color' value='{item.color}' required></label></p>
                            <p><label>Size Type:
                                <select name='size_type' id='edit_size_type' required>
                                    <option value='tshirt' {'selected' if item.size_type == 'tshirt' else ''}>T-Shirt</option>
                                    <option value='pants' {'selected' if item.size_type == 'pants' else ''}>Pants (waist x length)</option>
                                    <option value='shoes' {'selected' if item.size_type == 'shoes' else ''}>Shoes</option>
                                    <option value='other' {'selected' if item.size_type == 'other' else ''}>Other</option>
                                </select>
                            </label></p>

                            <div id='edit_tshirt_size' style='display:none'>
                            <p><label>Size:
                                <select name='size'>
                                    <option value=''>Select a size</option>
                                    {''.join(f"<option value='{option}'{' selected' if option == item.size else ''}>{option}</option>" for option in SIZE_OPTIONS)}
                                </select>
                            </label></p>
                            </div>

                            <div id='edit_pants_size' style='display:none'>
                                <p><label>Waist:
                                    <select name='pant_waist'>
                                        <option value=''>Waist</option>
                                        {''.join(f"<option value='{w}'{' selected' if item.pant_waist==w else ''}>{w}</option>" for w in PANT_WAIST_OPTIONS)}
                                    </select>
                                </label></p>
                                <p><label>Length:
                                    <select name='pant_length'>
                                        <option value=''>Length</option>
                                        {''.join(f"<option value='{l}'{' selected' if item.pant_length==l else ''}>{l}</option>" for l in PANT_LENGTH_OPTIONS)}
                                    </select>
                                </label></p>
                            </div>

                            <div id='edit_shoe_size' style='display:none'>
                                <p><label>Shoe size: <input name='shoe_size' value='{item.shoe_size or ""}' list='shoe_sizes'></label></p>
                                <datalist id='shoe_sizes'>{''.join(f"<option value='{s}'>" for s in SHOE_SIZES)}</datalist>
                            </div>

                            <p><label>Tags: <input name='tags' value='{item.tags or ""}'></label></p>
                            <button type='submit'>Save Changes</button>
                            <script>
                                (function(){{
                                    var sizeType = document.getElementById('edit_size_type');
                                    var tshirt = document.getElementById('edit_tshirt_size');
                                    var pants = document.getElementById('edit_pants_size');
                                    var shoe = document.getElementById('edit_shoe_size');
                                    function update(){{
                                        var v = sizeType.value;
                                        tshirt.style.display = v === 'tshirt' || v === 'other' ? '' : 'none';
                                        pants.style.display = v === 'pants' ? '' : 'none';
                                        shoe.style.display = v === 'shoes' ? '' : 'none';
                                    }}
                                    sizeType.addEventListener('change', update);
                                    update();
                                }})();
                            </script>
            </form>
          </body>
        </html>
        """
    finally:
        db.close()


@app.post("/items/{item_id}/update")
def update_item(request: Request, item_id: int, name: str = Form(...), category: str = Form(...), color: str = Form(...), size_type: str = Form('tshirt'), size: str = Form(''), pant_waist: int | None = Form(None), pant_length: int | None = Form(None), shoe_size: str = Form(''), tags: str = Form("")):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before editing items.")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id, ClothingItem.user_id == user.id).first()
        if not item:
            return render_page(request, user=user, error_message="Item not found.")

        item.name = name
        item.category = category
        item.color = color
        # map size fields based on size_type
        if size_type == 'pants':
            item.pant_waist = pant_waist
            item.pant_length = pant_length
            item.size = f"{pant_waist}x{pant_length}" if pant_waist and pant_length else item.size
            item.shoe_size = None
        elif size_type == 'shoes':
            item.shoe_size = shoe_size
            item.size = shoe_size
            item.pant_waist = None
            item.pant_length = None
        else:
            item.size = size
            item.pant_waist = None
            item.pant_length = None
            item.shoe_size = None
        item.size_type = size_type
        item.tags = ", ".join(tag.strip() for tag in tags.split(",") if tag.strip())
        db.commit()
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/items/{item_id}/delete")
def delete_item(request: Request, item_id: int):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before deleting items.")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id, ClothingItem.user_id == user.id).first()
        if not item:
            return render_page(request, user=user, error_message="Item not found.")

        if item.image_filename:
            image_path = UPLOAD_DIR / item.image_filename
            if image_path.exists():
                image_path.unlink(missing_ok=True)

        db.delete(item)
        db.commit()
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/items/{item_id}/favorite")
def toggle_favorite(request: Request, item_id: int):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before changing item preferences.")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id, ClothingItem.user_id == user.id).first()
        if not item:
            return render_page(request, user=user, error_message="Item not found.")

        item.favorite = 0 if item.favorite else 1
        db.commit()
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.post("/items/{item_id}/archive")
def toggle_archive(request: Request, item_id: int):
    db = SessionLocal()
    try:
        try:
            user = get_authenticated_user(request, db)
        except HTTPException:
            return render_page(request, error_message="Please log in before changing item preferences.")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id, ClothingItem.user_id == user.id).first()
        if not item:
            return render_page(request, user=user, error_message="Item not found.")

        item.archived = 0 if item.archived else 1
        db.commit()
        return RedirectResponse(url="/", status_code=303)
    finally:
        db.close()


@app.get("/items")
def list_items(request: Request):
    db = SessionLocal()
    try:
        user = get_authenticated_user(request, db)
        items = db.query(ClothingItem).filter(ClothingItem.user_id == user.id).order_by(ClothingItem.id.desc()).all()
        return [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "color": item.color,
                "size": item.size,
                "size_type": item.size_type,
                "pant_waist": item.pant_waist,
                "pant_length": item.pant_length,
                "shoe_size": item.shoe_size,
                "tags": item.tags,
                "image_filename": item.image_filename,
            }
            for item in items
        ]
    finally:
        db.close()


@app.post("/admin/users")
def admin_create_user(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        user = db.query(User).filter(User.session_token == session_token).first() if session_token else None
        if not user or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="admin access required")

        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return RedirectResponse(url="/admin?error=That+username+already+exists.", status_code=303)

        new_user = User(username=username, password_hash=hash_password(password))
        db.add(new_user)
        db.commit()
        return RedirectResponse(url="/admin?success=User+created+successfully.", status_code=303)
    finally:
        db.close()


@app.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    db = SessionLocal()
    try:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        user = db.query(User).filter(User.session_token == session_token).first() if session_token else None
        if not user or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="admin access required")

        target = db.query(User).filter(User.id == user_id).first()
        if not target or target.username == ADMIN_USERNAME:
            return RedirectResponse(url="/admin?error=User+could+not+be+removed.", status_code=303)

        db.query(ClothingItem).filter(ClothingItem.user_id == target.id).delete(synchronize_session=False)
        db.delete(target)
        db.commit()
        return RedirectResponse(url="/admin?success=User+removed+successfully.", status_code=303)
    finally:
        db.close()


@app.post("/admin/items/{item_id}/delete")
def admin_delete_item(request: Request, item_id: int):
    db = SessionLocal()
    try:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        user = db.query(User).filter(User.session_token == session_token).first() if session_token else None
        if not user or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="admin access required")

        item = db.query(ClothingItem).filter(ClothingItem.id == item_id).first()
        if not item:
            return RedirectResponse(url="/admin?error=Item+could+not+be+removed.", status_code=303)

        if item.image_filename:
            image_path = UPLOAD_DIR / item.image_filename
            if image_path.exists():
                image_path.unlink(missing_ok=True)

        db.delete(item)
        db.commit()
        return RedirectResponse(url="/admin?success=Item+removed+successfully.", status_code=303)
    finally:
        db.close()


@app.get("/admin", response_class=HTMLResponse)
def admin_portal(request: Request):
    db = SessionLocal()
    try:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        user = db.query(User).filter(User.session_token == session_token).first() if session_token else None
        if not user or not is_admin_user(user):
            raise HTTPException(status_code=403, detail="admin access required")

        users = db.query(User).order_by(User.id).all()
        user_rows = []
        for account in users:
            items = db.query(ClothingItem).filter(ClothingItem.user_id == account.id).order_by(ClothingItem.id.desc()).all()
            item_rows = "".join(
                f"<li>{item.name} ({item.category}, {item.color}, {item.size}) <form action='/admin/items/{item.id}/delete' method='post' style='display:inline'><button type='submit'>Remove Item</button></form></li>"
                for item in items
            )
            delete_user_form = "" if account.username == ADMIN_USERNAME else f"<form action='/admin/users/{account.id}/delete' method='post' style='display:inline'><button type='submit'>Remove User</button></form>"
            user_rows.append(
                f"<li><strong>{account.username}</strong> {delete_user_form}<ul>{item_rows or '<li>No items</li>'}</ul></li>"
            )

        alert = ""
        if request.query_params.get("error"):
            alert = f"<p style='padding:0.75rem;border:1px solid #b91c1c;background:#fee2e2;color:#991b1b;border-radius:6px'>{request.query_params['error']}</p>"
        if request.query_params.get("success"):
            alert = f"<p style='padding:0.75rem;border:1px solid #15803d;background:#dcfce7;color:#166534;border-radius:6px'>{request.query_params['success']}</p>"

        return f"""
        <html>
          <head><title>Admin Portal</title></head>
          <body style='font-family: sans-serif; max-width: 900px; margin: 2rem auto;'>
            <h1>Admin Portal</h1>
            <p>Manage signed-up users and their inventories.</p>
            <p><a href='/'>Back to inventory</a></p>
            {alert}
            <h2>Register User</h2>
            <form action='/admin/users' method='post'>
              <p><label>Username: <input name='username' required></label></p>
              <p><label>Password: <input type='password' name='password' required></label></p>
              <button type='submit'>Create User</button>
            </form>
            <h2>Users</h2>
            <ul>{''.join(user_rows)}</ul>
          </body>
        </html>
        """
    finally:
        db.close()
