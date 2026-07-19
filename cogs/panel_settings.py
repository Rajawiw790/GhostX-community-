"""
تخزين إعدادات تخصيص لوحات (Ticket Shop / Verify):
العنوان، الوصف، الفوتر، ونصوص وإيموجي الأزرار.
يُخزَّن كل شيء فـ MongoDB (collection: panel_settings) ويبقى بعد إعادة تشغيل البوت.
"""
import db

PANEL_SETTINGS_COLLECTION = "panel_settings"

DEFAULTS = {
    # ── Ticket Shop panel ──
    "shop_title": "🎫 Ticket System — {server}",
    "shop_description": None,   # None => يستعمل الوصف الافتراضي المبرمج
    "shop_footer": None,        # None => يستعمل "{bot} | Dev: {dev}"
    "shop_close_label": "إغلاق",       "shop_close_emoji": "🔒",
    "shop_claim_label": "Claim",       "shop_claim_emoji": "📋",
    "shop_done_label":  "تم التنفيذ",  "shop_done_emoji":  "✅",

    # ── أنواع التذكرة فالقائمة المنسدلة (Select Menu) ──
    "type_support_label": None, "type_support_desc": None, "type_support_emoji": None,
    "type_report_label":  None, "type_report_desc":  None, "type_report_emoji":  None,
    "type_shop_label":    None, "type_shop_desc":    None, "type_shop_emoji":    None,
    "type_apply_label":   None, "type_apply_desc":   None, "type_apply_emoji":   None,
    "type_partner_label": None, "type_partner_desc": None, "type_partner_emoji": None,
    "type_other_label":   None, "type_other_desc":   None, "type_other_emoji":   None,

    # ── Verify panel ──
    "verify_title": "🔐 التحقق — {server}",
    "verify_description": None,
    "verify_footer": None,
    "verify_button_label": "تحقق الآن",
    "verify_button_emoji": "✅",

    # ── Boost review panel ──
    "boost_title": "🌟 Boost Proof",
    "boost_description": None,   # None => default "Your proof has been submitted. Please wait for review."
    "boost_footer": None,
    "boost_accept_label": "Accept", "boost_accept_emoji": "✅",
    "boost_reject_label": "Reject", "boost_reject_emoji": "❌",

    # ── Subscribe review panel ──
    "subscribe_title": "🔔 Subscribe Proof",
    "subscribe_description": None,  # None => default "Your proof has been submitted. Please wait for review."
    "subscribe_footer": None,
    "subscribe_accept_label": "Accept", "subscribe_accept_emoji": "✅",
    "subscribe_reject_label": "Reject", "subscribe_reject_emoji": "❌",

    # ── Ticket panel (card look) ──
    "ticket_reason_label": "🗒️ Ticket Reason",
    "ticket_instructions_title": "📥 Important Ticket Instructions",
    "ticket_instructions_text": (
        "Please write what you need right away instead of waiting for staff to reply first — "
        "this avoids leaving your ticket empty for too long."
    ),
    "ticket_support_panel_label": "Support Panel",
    "ticket_support_panel_emoji": "🛠️",
}


def render(text: str) -> str:
    """يبدّل {server}/{bot}/{dev} بالقيم الحقيقية من config."""
    if not text:
        return text
    import config
    return (
        text.replace("{server}", getattr(config, "SERVER_NAME", ""))
            .replace("{bot}", getattr(config, "BOT_NAME", ""))
            .replace("{dev}", getattr(config, "DEVELOPER", ""))
    )


def _load() -> dict:
    data = db.load_doc(PANEL_SETTINGS_COLLECTION)
    return {**DEFAULTS, **data}


def _save(data: dict) -> None:
    db.save_doc(PANEL_SETTINGS_COLLECTION, data)


def get(key: str):
    return _load().get(key, DEFAULTS.get(key))


def get_all() -> dict:
    return _load()


def set_values(**kwargs) -> dict:
    """يحدّث فقط القيم اللي ماشي None، ويرجع الإعدادات الكاملة بعد الحفظ."""
    data = _load()
    for k, v in kwargs.items():
        if v is not None:
            data[k] = v
    _save(data)
    return data


async def setup(bot):
    """
    هاد الملف مجرد وحدة مساعدة (helper) كيتم استيرادها من cogs أخرى
    (from cogs import panel_settings) وماشي cog فيه أوامر.
    main.py كيحاول يحمّل كل ملفات .py لي فمجلد cogs/ كـ extension،
    فخاصها setup() فارغة باش ما يعطيش خطأ عند التشغيل.
    """
    pass
