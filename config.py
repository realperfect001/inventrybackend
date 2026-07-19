import os

# --- JWT settings ---
# IMPORTANT: override SECRET_KEY via environment variable in production.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))  # 8 hours

# --- Default admin, seeded only if no users exist yet ---
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")

# --- Shared secret the ESP32 must send in the "X-API-Key" header on /scan ---
# Change this and update the matching constant in the ESP32 sketch.
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "change-me-device-key")
