# Setting up MongoDB for the bot's data

Every cog that used to read/write a `.json` file in `data/` now reads and
writes MongoDB instead (see `db.py`). This survives host restarts, redeploys,
and (unlike a local JSON file) works even if the bot ever runs on more than
one machine.

The bot only needs a **connection string** — you don't have to self-host
anything. The free option below takes about 5 minutes.

## 1. Create a free MongoDB Atlas cluster

1. Go to [cloud.mongodb.com](https://cloud.mongodb.com) and sign up (email or
   Google/GitHub).
2. **Build a Database** → choose **Free** (the M0 tier — free forever, no
   card required, plenty for a bot this size).
3. Pick any cloud provider/region (closest to where the bot runs is fine) →
   **Create Deployment**. Takes 1–3 minutes to provision.
4. **Database Access** (left sidebar) → confirm/create a database user with
   a username + password (Atlas prompts for this right after cluster
   creation too). Save the password somewhere — you'll need it below.
5. **Network Access** (left sidebar) → **Add IP Address**. If the bot's host
   IP isn't fixed (e.g. Replit, a container platform, most PaaS hosts), add
   `0.0.0.0/0` (allow from anywhere) — fine for a bot whose only secret is
   in the password, not ideal for a bank.
6. Back on the cluster page, click **Connect** → **Drivers** → copy the
   connection string. It looks like:
   ```
   mongodb+srv://myapp-user:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Replace `<password>` with the real password from step 4.

## 2. Point the bot at it

In your `.env`:

```
MONGO_URI=mongodb+srv://myapp-user:yourpassword@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=ghostx
```

`MONGO_DB_NAME` can be anything — Atlas creates the database automatically
the first time the bot writes something. `ghostx` is just a sensible default.

## 3. Restart the bot

That's it — no migration script needed. Every setting (tickets, boost,
subscribe, reaction roles, welcome, panel customization, voice rooms, server
stats, etc.) starts saving to MongoDB from the next `/…setup` or `/…update`
command onward.

If `MONGO_URI` is missing or unreachable, the bot **won't crash** — `db.py`
fails soft: reads return empty (so cogs fall back to their built-in
defaults) and writes are silently skipped, with one warning printed to the
console the first time it happens. Everything that doesn't touch persistent
settings (moderation commands, music, etc.) keeps working either way.

## Notes

- The old `data/*.json` files are no longer read once this is set up. They're
  harmless leftovers — safe to delete, or keep as a backup/reference for
  manually re-entering settings if you want.
- One Atlas free cluster is plenty for this bot even across multiple
  Discord servers — everything is already scoped by guild ID inside each
  collection, the same way the old per-guild JSON entries were.
