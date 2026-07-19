"""
Embed Buttons — Ghostx Community
──────────────────────────────────
أضف أزرار على أي إمباد أرسله البوت — 3 أنواع:

  🔗 رابط     — يفتح رابطاً خارجياً
  🎭 رول      — يعطي / يشيل رولاً عند الضغط (toggle)
  🖱️ تفاعلي   — يرد برسالة مخفية عند الضغط

أوامر:
  /addbtn add    [message_id]  — أضف زراً (نافذة تعبئة)
  /addbtn remove [message_id]  — احذف كل أزرار الرسالة
  /addbtn list   [message_id]  — اعرض الأزرار الحالية
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db

COLLECTION = "embed_buttons"

STYLE_MAP = {
    "أزرق":  discord.ButtonStyle.primary,
    "رمادي": discord.ButtonStyle.secondary,
    "أخضر":  discord.ButtonStyle.success,
    "أحمر":  discord.ButtonStyle.danger,
}


# ── زر الرول (toggle) ────────────────────────────────────────────────────────
class _RoleButton(discord.ui.Button):
    """يعطي الرول إذا ما عنده — يشيله إذا عنده."""

    def __init__(self, *, label: str, emoji, style: discord.ButtonStyle, role_id: int):
        super().__init__(label=label, emoji=emoji, style=style)
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                "❌ الرول غير موجود — تواصل مع الإدارة.", ephemeral=True
            )
            return

        member = interaction.user
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="Embed button — role toggle")
                await interaction.response.send_message(
                    f"✅ تمت إزالة رول **{role.name}** منك.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ ليس لدي صلاحية لإزالة هذا الرول.", ephemeral=True
                )
        else:
            try:
                await member.add_roles(role, reason="Embed button — role toggle")
                await interaction.response.send_message(
                    f"🎭 حصلت على رول **{role.name}**!", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ ليس لدي صلاحية لإعطاء هذا الرول.", ephemeral=True
                )


# ── زر تفاعلي (رد نصي) ───────────────────────────────────────────────────────
class _CallbackButton(discord.ui.Button):
    def __init__(self, *, label: str, emoji, style: discord.ButtonStyle, reply_text: str):
        super().__init__(label=label, emoji=emoji, style=style)
        self.reply_text = reply_text

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.reply_text, ephemeral=True)


# ── View دائمة (تعيش بعد restart) ────────────────────────────────────────────
class PersistentButtonView(discord.ui.View):
    def __init__(self, buttons: list[dict]):
        super().__init__(timeout=None)
        for btn in buttons:
            label      = btn.get("label", "زر")
            emoji      = btn.get("emoji") or None
            style_name = btn.get("style", "أزرق")
            style      = STYLE_MAP.get(style_name, discord.ButtonStyle.primary)
            url        = btn.get("url") or None
            role_id    = btn.get("role_id") or None
            reply      = btn.get("reply", "✅ شكراً!")

            if url:
                # ── نوع 1: رابط ──────────────────────────────────────────────
                self.add_item(discord.ui.Button(
                    label=label, url=url, emoji=emoji,
                    style=discord.ButtonStyle.link,
                ))
            elif role_id:
                # ── نوع 2: رول ───────────────────────────────────────────────
                self.add_item(_RoleButton(
                    label=label, emoji=emoji, style=style,
                    role_id=int(role_id),
                ))
            else:
                # ── نوع 3: تفاعلي ────────────────────────────────────────────
                self.add_item(_CallbackButton(
                    label=label, emoji=emoji, style=style,
                    reply_text=reply,
                ))


# ── Modal: إضافة زر واحد ─────────────────────────────────────────────────────
class AddButtonModal(discord.ui.Modal, title="➕ إضافة زر على الإمباد"):
    btn_label = discord.ui.TextInput(
        label="نص الزر",
        placeholder="مثال: 🎭 احصل على الرول  |  🔗 الموقع  |  📩 تواصل",
        max_length=80,
        required=True,
    )
    btn_url = discord.ui.TextInput(
        label="🔗 رابط (للأزرار الخارجية — https://...)",
        placeholder="اتركه فارغاً إذا ما تريد رابطاً",
        required=False,
    )
    btn_role_id = discord.ui.TextInput(
        label="🎭 أيدي الرول (للأزرار التي تعطي رولاً)",
        placeholder="مثال: 123456789012345678 — اتركه فارغاً إذا لا تريد رولاً",
        required=False,
        max_length=25,
    )
    btn_reply = discord.ui.TextInput(
        label="🖱️ رد عند الضغط (للأزرار التفاعلية فقط)",
        placeholder="يُتجاهل إذا وضعت رابطاً أو رولاً",
        required=False,
        default="✅ شكراً على تفاعلك!",
    )
    btn_style_emoji = discord.ui.TextInput(
        label="لون | إيموجي  (مثال: أخضر | 🎭)",
        placeholder="أزرق / رمادي / أخضر / أحمر  و اختياري إيموجي بعد |",
        required=False,
        default="أزرق",
        max_length=60,
    )

    def __init__(self, channel_id: int, message_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # ── تحليل اللون والإيموجي ──────────────────────────────────────────
        raw_se = self.btn_style_emoji.value or "أزرق"
        parts  = [p.strip() for p in raw_se.split("|")]
        style_name = parts[0] if parts else "أزرق"
        emoji_raw  = parts[1] if len(parts) > 1 else None

        # ── تحقق من الرابط ────────────────────────────────────────────────
        url = self.btn_url.value.strip() or None
        if url and not url.startswith("http"):
            url = None

        # ── تحقق من الرول ────────────────────────────────────────────────
        role_id_raw = self.btn_role_id.value.strip() or None
        role_id     = None
        if role_id_raw:
            try:
                role_id = int(role_id_raw)
                # تأكد أن الرول موجود في السيرفر
                if not interaction.guild.get_role(role_id):
                    await interaction.followup.send(
                        f"❌ لم أجد رولاً بهذا الأيدي: `{role_id}` — تحقق من الرقم.",
                        ephemeral=True,
                    )
                    return
            except ValueError:
                await interaction.followup.send(
                    "❌ أيدي الرول يجب أن يكون رقماً فقط.", ephemeral=True
                )
                return

        # ── تحديد النوع ──────────────────────────────────────────────────
        if url:
            kind = "رابط 🔗"
        elif role_id:
            role = interaction.guild.get_role(role_id)
            kind = f"رول 🎭 ({role.name})"
        else:
            kind = "تفاعلي 🖱️"

        # ── تحميل الأزرار الموجودة ────────────────────────────────────────
        raw: dict     = db.load(COLLECTION)
        key           = str(self.message_id)
        existing: list = raw.get(key, {}).get("buttons", [])

        if len(existing) >= 5:
            await interaction.followup.send(
                "❌ لا يمكن إضافة أكثر من **5 أزرار** على نفس الرسالة.", ephemeral=True
            )
            return

        new_btn = {
            "label":   self.btn_label.value.strip(),
            "url":     url,
            "role_id": role_id,
            "reply":   self.btn_reply.value.strip() or "✅ شكراً على تفاعلك!",
            "emoji":   emoji_raw,
            "style":   style_name,
        }
        existing.append(new_btn)

        # ── حفظ وتعديل الرسالة ────────────────────────────────────────────
        raw[key] = {"channel_id": self.channel_id, "buttons": existing}
        db.save(COLLECTION, raw)

        try:
            channel = interaction.client.get_channel(self.channel_id)
            msg     = await channel.fetch_message(self.message_id)
            view    = PersistentButtonView(existing)
            await msg.edit(view=view)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ تمت إضافة الزر",
                    description=(
                        f"**الزر:** `{new_btn['label']}`\n"
                        f"**النوع:** {kind}\n"
                        f"**إجمالي الأزرار:** {len(existing)}/5"
                    ),
                    color=config.SUCCESS_COLOR,
                ),
                ephemeral=True,
            )
        except (discord.Forbidden, discord.NotFound) as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)


# ── Cog ──────────────────────────────────────────────────────────────────────
class EmbedButtons(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """أعد تسجيل الـ views عند إعادة تشغيل البوت."""
        raw: dict = db.load(COLLECTION)
        count     = 0
        for msg_id_str, val in raw.items():
            buttons = val.get("buttons", [])
            if buttons:
                view = PersistentButtonView(buttons)
                self.bot.add_view(view, message_id=int(msg_id_str))
                count += 1
        if count:
            print(f"  ✅ Embed buttons: {count} رسالة مُعادة تسجيلها")

    # ── Group ────────────────────────────────────────────────────────────────
    addbtn = app_commands.Group(
        name="addbtn",
        description="🔘 إضافة وإدارة أزرار على إمبادات البوت",
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @addbtn.command(name="add", description="➕ أضف زراً على إمباد البوت")
    @app_commands.describe(message_id="أيدي الرسالة (ID) التي تحتوي الإمباد")
    async def add_button(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("❌ أيدي الرسالة غير صحيح.", ephemeral=True)
            return

        try:
            msg = await interaction.channel.fetch_message(mid)
        except discord.NotFound:
            await interaction.response.send_message("❌ لم أجد الرسالة في هذا الروم.", ephemeral=True)
            return

        if msg.author.id != self.bot.user.id:
            await interaction.response.send_message(
                "❌ يمكنني فقط إضافة أزرار على **رسائل البوت** نفسه.", ephemeral=True
            )
            return

        modal = AddButtonModal(channel_id=interaction.channel.id, message_id=mid)
        await interaction.response.send_modal(modal)

    @addbtn.command(name="remove", description="🗑️ احذف كل الأزرار من رسالة")
    @app_commands.describe(message_id="أيدي الرسالة التي تريد حذف أزرارها")
    async def remove_buttons(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            mid = int(message_id)
            msg = await interaction.channel.fetch_message(mid)
            if msg.author.id != self.bot.user.id:
                await interaction.followup.send("❌ هذه ليست رسالة البوت.", ephemeral=True)
                return
            await msg.edit(view=None)

            raw = db.load(COLLECTION)
            raw.pop(str(mid), None)
            db.save(COLLECTION, raw)

            await interaction.followup.send(
                embed=discord.Embed(
                    title="🗑️ تم حذف الأزرار",
                    description="تمت إزالة جميع الأزرار من الرسالة.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)

    @addbtn.command(name="list", description="📋 اعرض الأزرار الموجودة على رسالة")
    @app_commands.describe(message_id="أيدي الرسالة")
    async def list_buttons(self, interaction: discord.Interaction, message_id: str):
        raw = db.load(COLLECTION)
        val = raw.get(message_id.strip())
        if not val or not val.get("buttons"):
            await interaction.response.send_message(
                "❌ لا توجد أزرار مسجّلة لهذه الرسالة.", ephemeral=True
            )
            return

        lines = []
        for i, b in enumerate(val["buttons"], 1):
            if b.get("url"):
                kind = f"🔗 {b['url']}"
            elif b.get("role_id"):
                role = interaction.guild.get_role(int(b["role_id"]))
                kind = f"🎭 رول: {role.name if role else b['role_id']}"
            else:
                kind = "🖱️ تفاعلي"
            lines.append(f"**{i}.** `{b['label']}` — {kind}")

        embed = discord.Embed(
            title="📋 أزرار الرسالة",
            description="\n".join(lines),
            color=config.EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedButtons(bot))
