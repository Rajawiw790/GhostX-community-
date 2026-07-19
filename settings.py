"""
نظام الإعدادات الدائمة — يحفظ كل شيء في settings.json
بدلاً من config.py الذي يُعاد تعيينه عند كل ريستارت
"""
import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

DEFAULTS = {
    # ── الترحيب ──
    "welcome_channel_id": None,
    "welcome_log_channel_id": None,
    "welcome_auto_role_id": None,
    "welcome_bg_url": "",
    "welcome_message": "",

    # ── بانرات (محفوظة بشكل دائم، بعكس config.py اللي كيتصفر عند الريستارت) ──
    "verify_banner_url": "",
    "shop_banner_url": "",

    # ── الستاف ──
    "staff_app_channel_id": None,
    "staff_review_channel_id": None,
    "staff_role_id": None,
    "staff_questions": [
        "ما اسمك وعمرك؟",
        "كم ساعة يمكنك تخصيصها للسيرفر يومياً؟",
        "هل لديك خبرة سابقة في الإدارة؟ اشرح.",
        "لماذا تريد الانضمام لفريق الستاف؟",
        "كيف ستتعامل مع عضو يخالف القوانين؟",
    ],
}

def _load() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # دمج مع الافتراضيات لضمان وجود كل المفاتيح
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return dict(DEFAULTS)

def _save(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── واجهة عامة ──
def get(key: str):
    return _load().get(key, DEFAULTS.get(key))

def set(key: str, value):
    data = _load()
    data[key] = value
    _save(data)

def set_many(updates: dict):
    data = _load()
    data.update(updates)
    _save(data)

def all_settings() -> dict:
    return _load()
