"""
AI Chat — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━
/ai ask <question>   — اسأل الـ AI
/ai clear            — امسح محادثتك
/ai setup #channel   — عين روم للرد التلقائي
/ai remove           — ألغي الروم
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
import os
import time

# ── سجل المحادثات لكل يوزر ───────────────────────────────────────────────────
_histories: dict[int, list[dict]] = {}
MAX_HISTORY = 10

# ── رومات الـ AI التلقائية ────────────────────────────────────────────────────
_ai_channels: dict[int, int] = {}

# ── كاش لخريطة القنوات (باش ما نبنيوهاش فـ كل رسالة) ─────────────────────────
_channels_cache: dict[int, tuple[float, str]] = {}
CHANNELS_CACHE_TTL = 300  # 5 دقايق

GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

AI_CHANNELS_COLLECTION = "ai_channels"

# ── System Prompt — معلومات السيرفر الصحيحة ──────────────────────────────────
SYSTEM_PROMPT = """
أنت Ghostx AI، مساعد ذكي ورسمي داخل سيرفر Ghostx Community على Discord.

========================
دورك (Role)
========================

أنت هنا لِـ:
- الرد على أسئلة الأعضاء بشكل واضح ومباشر.
- إرشاد الأعضاء للروم الصحيح حسب حاجتهم (سكريبتات، مساعدة، تذاكر...).
- تفسير قوانين السيرفر عند الطلب.
- الدردشة العامة فـ أي موضوع (برمجة، علوم، ألعاب، تاريخ، رياضيات...) بلا قيود على المواضيع، ما عدا المحتوى المخالف لقوانين Discord.
- ما بقاش من صلاحياتك: كيك، باند، ميوت، تعديل رتب — هادشي مهمة الإدارة والبوتات المختصة، خبر العضو يفتح تذكرة أو يتصل بالإدارة.

إذا سولك شخص "شنو نتا؟" أو "واش نتا بوت ولا إنسان؟" قول بصراحة أنك AI مساعد فـ السيرفر، ماشي إنسان.

========================
معلومات السيرفر
========================

الاسم:
Ghostx Community

المؤسس والمطور:
GhostX 

التخصص:
- San Andreas Multiplayer (SAMP)
- open.mp
- Pawn
- Filterscripts
- Gamemodes
- Discord Bots
- البرمجة
- نشر الموارد
- مساعدة المطورين
- Community عربي

السيرفر مخصص للمطورين واللاعبين لمشاركة المشاريع والسكريبتات والموارد والمساعدة التقنية.

========================
معلومات إضافية
========================

إذا سأل أي شخص عن سيرفر رول بلاي:

يوجد أيضاً سيرفر:

Fastlife RolePlay

رابطه:

https://discord.gg/UVAAgyANK

اذكره فقط عندما يكون السؤال عن الرول بلاي أو سيرفرات RP.

========================
قوانين السيرفر
========================

إذا طلب أحد القوانين أو Rules أو قوانين السيرفر فأرسل له:

**قوانين الأعضاء**

• احترام جميع الأعضاء دون استثناء.
• يمنع السب أو العنصرية أو الاستفزاز.
• يمنع السبام والإزعاج.
• استخدم كل روم في الغرض المخصص له.

**الممنوعات**

• يمنع نشر الإعلانات أو الروابط بدون إذن.
• يمنع انتحال شخصية الإدارة.
• يمنع نشر المحتوى المخالف.
• يمنع استغلال الثغرات أو التخريب.
• يمنع إثارة المشاكل والفتن.

**الإدارة**

• احترام جميع قرارات الإدارة.
• يمنع طلب الرتب الإدارية.
• يمنع مناقشة العقوبات في الشات العام.
• عند وجود مشكلة افتح Ticket.

**العقوبات**

• المخالفة الأولى: تحذير.
• الثانية: ميوت مؤقت.
• الثالثة: كيك أو باند مؤقت.
• المخالفات الجسيمة: باند دائم.

========================
الإرشاد داخل السيرفر (استعمل لائحة القنوات فـ الأسفل)
========================

عندك لائحة "قنوات السيرفر" غادي تجيك فـ آخر هاد الرسالة، منظمة بالكاتيغوري، وفيها وصف كل روم (إلا كان عندو topic محدد).

إذا سأل شخص:
- أين أجد السكريبتات؟
- أين أنشر مشروعي؟
- أين أرفع الموارد؟
- أين أطلب المساعدة؟
- أين أفتح تذكرة؟

شوف فـ اللائحة أقرب روم مناسب باسمو أو بالوصف ديالو، وقترحو عليه بصيغة #اسم-الروم.

إذا ما لقيتيش روم واضح فلا تخترع أسماء، قول له يسول فـ الروم العام أو يتصل بالإدارة.

========================
عن السيرفر
========================

إذا سأل المستخدم:

من صاحب السيرفر؟

أجب:

المؤسس والمطور هو GhostX.

إذا سأل:

ما هو Ghostx Community؟

أجب بأنه مجتمع عربي يهتم بتطوير SAMP و open.mp والبرمجة والموارد ومشاركة المشاريع.

========================
أسئلة عامة
========================

لا تقتصر على معلومات السيرفر فقط.

أجب أيضاً عن أي موضوع عام يسولو عليه المستخدم:
- البرمجة (Python, JS, C++...)
- Discord.py / discord.js
- Pawn / open.mp / SAMP
- Discord Bots
- GitHub / Git
- Linux
- الذكاء الاصطناعي
- الألعاب
- الرياضيات
- التاريخ
- العلوم
- الحياة اليومية، النصائح، أي سؤال عام آخر

إذا كان السؤال خارج موضوع السيرفر فأجب عليه بشكل طبيعي وكامل، بلا ما تحصر جوابك فـ موضوع السيرفر.

========================
أسلوب الرد
========================

- رد بنفس لغة المستخدم (دارجة، عربية فصحى، فرنسية أو إنجليزية حسب سؤاله).
- لا تقل:
  "بالطبع"
  "بكل سرور"
  "سؤال رائع"

- كن مختصراً إذا كان السؤال بسيطاً.
- كن مفصلاً إذا طلب شرحاً.
- لا تدّع أنك إنسان.
- لا تخترع معلومات (روم، رتبة، قانون...) ما كانت فـ المعطيات لي عندك.
- إذا لم تعرف الجواب قل بصراحة "لا أعرف" بدل التخمين.
"""


def _load_ai_channels():
    global _ai_channels
    data = db.load(AI_CHANNELS_COLLECTION)
    _ai_channels = {
        int(k): int(v.get("channel_id", 0))
        for k, v in data.items() if v.get("channel_id")
    }


def _save_ai_channels():
    data = {str(gid): {"channel_id": cid} for gid, cid in _ai_channels.items()}
    db.save(AI_CHANNELS_COLLECTION, data)


def _build_channels_context(guild: discord.Guild) -> str:
    """
    كتبني نص منظم بالكاتيغوري يوصف قنوات السيرفر، باش الـ AI يقدر
    يرشد الأعضاء للروم الصحيح. كتستعمل كاش (5 دقايق) باش ما تعاود
    تبني اللائحة فـ كل رسالة.
    """
    now = time.time()
    cached = _channels_cache.get(guild.id)
    if cached and (now - cached[0]) < CHANNELS_CACHE_TTL:
        return cached[1]

    everyone = guild.default_role
    lines: list[str] = []

    for category in guild.categories:
        visible_channels = []
        for channel in category.text_channels:
            perms = channel.permissions_for(everyone)
            if not perms.view_channel:
                continue  # روم خاص بالإدارة/رتب معينة، ما نوريهوش للـ AI كخيار عام
            desc = f" — {channel.topic}" if channel.topic else ""
            visible_channels.append(f"  • #{channel.name}{desc}")

        if visible_channels:
            lines.append(f"[{category.name}]")
            lines.extend(visible_channels)

    # قنوات بلا كاتيغوري
    uncategorized = []
    for channel in guild.text_channels:
        if channel.category is None:
            perms = channel.permissions_for(everyone)
            if not perms.view_channel:
                continue
            desc = f" — {channel.topic}" if channel.topic else ""
            uncategorized.append(f"  • #{channel.name}{desc}")
    if uncategorized:
        lines.append("[بدون كاتيغوري]")
        lines.extend(uncategorized)

    result = "\n".join(lines) if lines else "لا توجد قنوات عامة معروفة."
    _channels_cache[guild.id] = (now, result)
    return result


async def _ask_groq(guild: discord.Guild, uid: int, question: str) -> str:
    from openai import AsyncOpenAI

    if uid not in _histories:
        _histories[uid] = []

    _histories[uid].append({"role": "user", "content": question})
    if len(_histories[uid]) > MAX_HISTORY * 2:
        _histories[uid] = _histories[uid][-MAX_HISTORY * 2:]

    channels_context = _build_channels_context(guild)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + f"\n\nقنوات السيرفر (بالكاتيغوري):\n{channels_context}"
        },
        *_histories[uid]
    ]

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    client  = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    response = await client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=800,
        temperature=0.7,
    )
    answer = response.choices[0].message.content.strip()
    _histories[uid].append({"role": "assistant", "content": answer})
    return answer


# ── Slash Group ───────────────────────────────────────────────────────────────
class AIGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="ai", description="🤖 Ghostx AI — powered by Groq")
        self.bot = bot

    @app_commands.command(name="ask", description="🤖 اسأل الـ AI أي سؤال")
    @app_commands.describe(question="سؤالك للـ AI")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()

        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            await interaction.followup.send(
                "❌ `GROQ_API_KEY` مش مضاف — تواصل مع الإدارة.", ephemeral=True
            )
            return

        try:
            answer = await _ask_groq(interaction.guild, interaction.user.id, question)
            display = answer if len(answer) <= 1900 else answer[:1897] + "..."
            await interaction.followup.send(f"**{interaction.user.display_name}:** {question}\n\n{display}")
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ في الـ AI: `{str(e)[:300]}`", ephemeral=True)

    @app_commands.command(name="clear", description="🗑️ امسح محادثتك مع الـ AI")
    async def clear(self, interaction: discord.Interaction):
        _histories.pop(interaction.user.id, None)
        await interaction.response.send_message("✅ تم مسح سجل محادثتك.", ephemeral=True)

    @app_commands.command(name="setup", description="📌 عين روم يرد فيه الـ AI تلقائياً")
    @app_commands.describe(channel="الروم اللي بغيت البوت يرد فيه")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        _ai_channels[interaction.guild_id] = channel.id
        _save_ai_channels()
        await interaction.response.send_message(
            f"✅ تم — البوت دابا يرد في {channel.mention} على كل رسالة.\n"
            f"باش تلغيه: `/ai remove`",
            ephemeral=True,
        )

    @app_commands.command(name="remove", description="❌ ألغي الـ AI Room")
    @app_commands.default_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction):
        if interaction.guild_id in _ai_channels:
            del _ai_channels[interaction.guild_id]
            _save_ai_channels()
            await interaction.response.send_message("✅ تم إلغاء الـ AI Room.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ ما كاين حتى روم مسيتاب.", ephemeral=True)

    @app_commands.command(name="refresh_channels", description="🔄 حدّث لائحة القنوات لي كايشوف الـ AI")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh_channels(self, interaction: discord.Interaction):
        _channels_cache.pop(interaction.guild_id, None)
        _build_channels_context(interaction.guild)
        await interaction.response.send_message("✅ تم تحديث خريطة القنوات.", ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────────────────
class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._group = AIGroup(bot)
        bot.tree.add_command(self._group)
        _load_ai_channels()

    async def cog_unload(self):
        self.bot.tree.remove_command("ai")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        channel_id = _ai_channels.get(message.guild.id)
        if not channel_id or message.channel.id != channel_id:
            return
        content = message.content.strip()
        if not content or content.startswith("/") or content.startswith("!"):
            return

        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            return

        async with message.channel.typing():
            try:
                answer = await _ask_groq(message.guild, message.author.id, content)
                display = answer if len(answer) <= 1900 else answer[:1897] + "..."
                await message.reply(display, mention_author=False)
            except Exception:
                pass   # صامت — لا يبعت رسالة خطأ في الروم العام


async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
