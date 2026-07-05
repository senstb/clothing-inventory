import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as test_client:
        yield test_client

    os.remove(db_path)


def test_root_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Clothing Inventory" in response.text
    assert "Sign up" in response.text
    assert "Log in" in response.text
    assert "Add Item" not in response.text


def test_add_item_form_contains_category_and_size_dropdowns(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    response = client.get("/")
    assert response.status_code == 200
    assert "<select name='category'" in response.text
    assert "option value='Top'" in response.text
    assert "<select name='size'" in response.text
    assert "option value='M'" in response.text
    assert "name='tags'" in response.text


def test_tag_filter_shows_only_matching_items(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    client.post(
        "/items",
        data={"name": "Blue Shirt", "category": "Top", "color": "Blue", "size": "M", "tags": "casual, work"},
        files={},
        follow_redirects=False,
    )
    client.post(
        "/items",
        data={"name": "Black Suit", "category": "Bottom", "color": "Black", "size": "L", "tags": "formal"},
        files={},
        follow_redirects=False,
    )

    response = client.get("/", params={"tag": "casual"})
    assert response.status_code == 200
    assert "Blue Shirt" in response.text
    assert "Black Suit" not in response.text


def test_pants_and_shoes_sizing(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    client.post(
        "/items",
        data={"name": "Jeans", "category": "Bottom", "color": "Blue", "size_type": "pants", "pant_waist": "32", "pant_length": "34", "tags": "casual"},
        files={},
        follow_redirects=False,
    )

    client.post(
        "/items",
        data={"name": "Sneakers", "category": "Shoes", "color": "White", "size_type": "shoes", "shoe_size": "10", "tags": "casual"},
        files={},
        follow_redirects=False,
    )

    response = client.get("/")
    assert response.status_code == 200
    assert "32x34" in response.text
    assert "10" in response.text


def test_create_and_list_item(client):
    signup_response = client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    assert signup_response.status_code == 303
    assert signup_response.headers["location"] == "/"

    login_response = client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"

    response = client.post(
        "/items",
        data={"name": "Blue Shirt", "category": "Top", "color": "Blue", "size": "M"},
        files={},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    list_response = client.get("/items")
    assert list_response.status_code == 200
    assert any(item["name"] == "Blue Shirt" for item in list_response.json())


def test_logged_in_user_sees_inventory_controls(client):
    client.post("/signup", data={"username": "alice", "password": "pw"})
    client.post("/login", data={"username": "alice", "password": "pw"})

    response = client.get("/")
    assert response.status_code == 200
    assert "Logged in as alice" in response.text
    assert "Add Item" in response.text
    assert "Log out" in response.text


def test_outfit_template_can_be_created_from_matching_items(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    client.post(
        "/items",
        data={"name": "Blue Shirt", "category": "Top", "color": "Blue", "size": "M", "tags": "work, casual"},
        files={},
        follow_redirects=False,
    )
    client.post(
        "/items",
        data={"name": "Black Pants", "category": "Bottom", "color": "Black", "size": "L", "tags": "work"},
        files={},
        follow_redirects=False,
    )

    template_response = client.post(
        "/outfits",
        data={"name": "Workday", "tags": "work"},
        follow_redirects=False,
    )
    assert template_response.status_code == 303

    list_response = client.get("/")
    assert list_response.status_code == 200
    assert "Workday" in list_response.text
    assert "Blue Shirt" in list_response.text


def test_users_can_update_and_remove_inventory_items(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    create_response = client.post(
        "/items",
        data={"name": "Blue Shirt", "category": "Top", "color": "Blue", "size": "M", "tags": "casual"},
        files={},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    update_response = client.post(
        "/items/1/update",
        data={"name": "Navy Shirt", "category": "Top", "color": "Navy", "size": "L", "tags": "casual, work"},
        follow_redirects=False,
    )
    assert update_response.status_code == 303

    delete_response = client.post("/items/1/delete", follow_redirects=False)
    assert delete_response.status_code == 303

    inventory_page = client.get("/")
    assert inventory_page.status_code == 200
    assert "Navy Shirt" not in inventory_page.text
    assert "Blue Shirt" not in inventory_page.text


def test_users_can_toggle_favorite_and_archive_state(client):
    client.post("/signup", data={"username": "tester", "password": "secret"}, follow_redirects=False)
    client.post("/login", data={"username": "tester", "password": "secret"}, follow_redirects=False)

    client.post(
        "/items",
        data={"name": "Blue Shirt", "category": "Top", "color": "Blue", "size": "M", "tags": "casual"},
        files={},
        follow_redirects=False,
    )

    favorite_response = client.post("/items/1/favorite", follow_redirects=False)
    assert favorite_response.status_code == 303

    archive_response = client.post("/items/1/archive", follow_redirects=False)
    assert archive_response.status_code == 303

    inventory_page = client.get("/")
    assert inventory_page.status_code == 200
    assert "Favorite" in inventory_page.text
    assert "Archived" in inventory_page.text


def test_admin_portal_is_available_with_default_credentials(client):
    admin_login = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert admin_login.status_code == 303

    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin Portal" in response.text
    assert "admin" in response.text


def test_unauthorized_admin_access_shows_notice(client):
    response = client.get("/admin")
    assert response.status_code == 403
    assert "Admin access is required" in response.text


def test_admin_can_create_and_remove_users_and_items(client):
    admin_login = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert admin_login.status_code == 303

    create_user = client.post("/admin/users", data={"username": "tempuser", "password": "pw"}, follow_redirects=False)
    assert create_user.status_code == 303

    client.post("/login", data={"username": "tempuser", "password": "pw"}, follow_redirects=False)
    client.post(
        "/items",
        data={"name": "Temp Jacket", "category": "Outerwear", "color": "Black", "size": "L"},
        files={},
        follow_redirects=False,
    )

    client.post("/logout", follow_redirects=False)
    client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    admin_page = client.get("/admin")
    assert admin_page.status_code == 200
    assert "tempuser" in admin_page.text

    delete_item = client.post("/admin/items/1/delete", follow_redirects=False)
    assert delete_item.status_code == 303

    delete_user = client.post("/admin/users/2/delete", follow_redirects=False)
    assert delete_user.status_code == 303


def test_users_have_isolated_inventories(client):
    client.post("/signup", data={"username": "alice", "password": "pw"}, follow_redirects=False)
    client.post("/signup", data={"username": "bob", "password": "pw"}, follow_redirects=False)

    client.post("/login", data={"username": "alice", "password": "pw"}, follow_redirects=False)
    client.post(
        "/items",
        data={"name": "Red Dress", "category": "Dress", "color": "Red", "size": "S"},
        files={},
        follow_redirects=False,
    )

    client.post("/logout", follow_redirects=False)
    client.post("/login", data={"username": "bob", "password": "pw"}, follow_redirects=False)

    list_response = client.get("/items")
    assert list_response.status_code == 200
    assert list_response.json() == []
