"""
============================================================
  رافع الإيموجي التلقائي — شغّله مرة واحدة فقط!
  يرفع كل الإيموجي إلى Application Emojis ديال البوت
  بعدها يستخدمها البوت تلقائياً في كل رسائله وأزراره
============================================================
  طريقة التشغيل:
    1. تأكد أن DISCORD_TOKEN في ملف .env
    2. شغّل: python upload_emojis.py
    3. انتظر حتى يتم رفع كل الإيموجي
    4. شغّل البوت بشكل طبيعي
============================================================
"""
import os
import asyncio
import aiohttp
from pathlib import Path
import base64
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
if not TOKEN:
    print("❌ لم يتم العثور على DISCORD_TOKEN في ملف .env")
    exit(1)

EMOJI_DIR = Path(__file__).parent / "bot_emojis"


async def get_application_id(session: aiohttp.ClientSession) -> str:
    async with session.get(
        "https://discord.com/api/v10/oauth2/applications/@me",
        headers={"Authorization": f"Bot {TOKEN}"}
    ) as resp:
        if resp.status != 200:
            print(f"❌ فشل جلب معلومات التطبيق: {resp.status}")
            exit(1)
        data = await resp.json()
        return data["id"]


async def get_existing_emojis(session: aiohttp.ClientSession, app_id: str) -> dict:
    async with session.get(
        f"https://discord.com/api/v10/applications/{app_id}/emojis",
        headers={"Authorization": f"Bot {TOKEN}"}
    ) as resp:
        if resp.status != 200:
            return {}
        data = await resp.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return {e["name"]: e["id"] for e in items}


async def upload_emoji(session: aiohttp.ClientSession, app_id: str, name: str, file_path: Path) -> bool:
    ext = file_path.suffix.lower()
    mime = "image/gif" if ext == ".gif" else "image/png"
    image_data = base64.b64encode(file_path.read_bytes()).decode()
    image_str = f"data:{mime};base64,{image_data}"

    async with session.post(
        f"https://discord.com/api/v10/applications/{app_id}/emojis",
        headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
        json={"name": name, "image": image_str}
    ) as resp:
        if resp.status in (200, 201):
            return True
        err = await resp.json()
        print(f"   ⚠️  {name}: {err.get('message', err)}")
        return False


async def delete_emoji(session: aiohttp.ClientSession, app_id: str, emoji_id: str):
    async with session.delete(
        f"https://discord.com/api/v10/applications/{app_id}/emojis/{emoji_id}",
        headers={"Authorization": f"Bot {TOKEN}"}
    ) as resp:
        return resp.status == 204


async def main():
    print("=" * 50)
    print("  🚀 رافع Application Emojis")
    print("=" * 50)

    if not EMOJI_DIR.exists():
        print(f"❌ المجلد غير موجود: {EMOJI_DIR}")
        return

    emoji_files = list(EMOJI_DIR.glob("fl_*.*"))
    if not emoji_files:
        print("❌ لا توجد إيموجي في مجلد bot_emojis/")
        return

    print(f"📂 وجدت {len(emoji_files)} إيموجي للرفع")

    async with aiohttp.ClientSession() as session:
        app_id = await get_application_id(session)
        print(f"✅ Application ID: {app_id}\n")

        existing = await get_existing_emojis(session, app_id)
        print(f"📋 الإيموجي الموجودة حالياً: {len(existing)}")

        uploaded = 0
        skipped = 0
        failed = 0

        for file_path in sorted(emoji_files):
            name = file_path.stem  # fl_verify, fl_check ...

            if name in existing:
                print(f"  ⏭️  موجود مسبقاً: {name}")
                skipped += 1
                continue

            print(f"  📤 رفع: {name} ({file_path.name})", end="", flush=True)
            success = await upload_emoji(session, app_id, name, file_path)
            if success:
                print(" ✅")
                uploaded += 1
            else:
                failed += 1

            # تأخير لتجنب Rate Limit
            await asyncio.sleep(1.2)

    print("\n" + "=" * 50)
    print(f"  ✅ تم الرفع:    {uploaded}")
    print(f"  ⏭️  موجود مسبقاً: {skipped}")
    print(f"  ❌ فشل:         {failed}")
    print("=" * 50)
    if failed == 0:
        print("🎉 تم رفع كل الإيموجي! شغّل البوت الآن.")
    else:
        print("⚠️  بعض الإيموجي فشلت — تحقق من الأخطاء أعلاه.")


if __name__ == "__main__":
    asyncio.run(main())
