"""
نظام تحميل Application Emojis أوتوماتيك.
الإيموجي مرفوعين يدوياً من Developer Portal بأسماء مختلفة عن الأسماء
الدلالية (fl_check, fl_verify...) لي كيستعملها باقي الكود.
NAME_MAP هي الجسر بين الاثنين: الكود كيطلب "fl_check" وهادشي كيترجمها
للاسم الحقيقي "40197checkmarkids" لي فالـ Developer Portal.
"""
import discord
from discord.ext import commands

# ── مطابقة: الاسم الدلالي (مستعمل فالكود) ← الاسم الحقيقي (Developer Portal) ──
NAME_MAP = {
    # التحقق / علامات
    "fl_verify":       "3882verify",
    "fl_verified":     "80012verified",
    "fl_check":        "40197checkmarkids",
    "fl_x":            "31274xids",
    "fl_warning":      "82728warningids",
    "fl_locked":       "3409locked",
    "fl_forbidden":    "21883forbidden",
    "fl_ban":          "579518ban",

    # رتب الستاف
    "fl_owner":        "53879owner",
    "fl_admin":        "904589admin",
    "fl_mod":          "852666moderator",
    "fl_staff":        "72151staff",
    "fl_trial_staff":  "720437trialstaff",
    "fl_developer":    "68223developerrubyshiny",
    "fl_vip":          "62392viprubyshiny",
    "fl_support":      "15447supportrubyshiny",
    "fl_member":       "18690member",

    # متنوعة
    "fl_raid":         "74999raid",
    "fl_boost":        "5156blackboost",
    "fl_loading":      "31830redloading",

    # أسهم متحركة
    "fl_arrow_green":  "68523animatedarrowgreen",
    "fl_arrow_blue":   "91490animatedarrowblue",
    "fl_arrow_red":    "73288animatedarrowred",
    "fl_arrow_purple": "73288animatedarrowpurple",
    "fl_arrow_pink":   "33214animatedarrowpink",
    "fl_arrow_orange": "28079animatedarroworange",
    "fl_arrow_yellow": "15770animatedarrowyellow",
    "fl_arrow_white":  "51047animatedarrowwhite",
}

EMOJI_NAMES = list(NAME_MAP.keys())

# ── الـ cache — يُملأ عند on_ready ────────────────────────────────────────
_emoji_cache: dict[str, discord.Emoji] = {}


def get(name: str) -> str:
    """
    ارجع الإيموجي كنص جاهز (مثل: <:verify:123456>).
    تقدر تعطيها الاسم الدلالي (fl_check) ولا الاسم الحقيقي مباشرة.
    إذا ما وُجدش يرجع نص فارغ بدل ما يكرّش.
    """
    real_name = NAME_MAP.get(name, name)
    emoji = _emoji_cache.get(real_name)
    return str(emoji) if emoji else ""


def get_obj(name: str):
    """ارجع كائن discord.Emoji مباشرة (للاستخدام في emoji= داخل Button)."""
    real_name = NAME_MAP.get(name, name)
    return _emoji_cache.get(real_name)


async def load_emojis(bot: commands.Bot):
    """احمّل كل Application Emojis من Discord API."""
    global _emoji_cache
    try:
        app_emojis = await bot.fetch_application_emojis()
        _emoji_cache = {e.name: e for e in app_emojis}

        loaded  = [k for k, v in NAME_MAP.items() if v in _emoji_cache]
        missing = [k for k, v in NAME_MAP.items() if v not in _emoji_cache]

        print(f"✅ Application Emojis: {len(loaded)}/{len(NAME_MAP)} محمّلة")
        if missing:
            print(f"⚠️  ناقص في Dev Portal: {', '.join(missing)}")
    except Exception as e:
        print(f"⚠️  فشل تحميل Application Emojis: {e}")
        _emoji_cache = {}


class EmojiLoader(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await load_emojis(self.bot)


async def setup(bot):
    await bot.add_cog(EmojiLoader(bot))
