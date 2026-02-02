"""Background worker for warmup system."""

import asyncio
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.modules.warmup import warmup_manager


async def warmup_send_task():
    """Send warmup emails between registered accounts."""
    print(f"[{datetime.utcnow()}] Running warmup send task...")

    active_accounts = [
        (email, acc) for email, acc in warmup_manager.accounts.items()
        if acc.get("is_active", False)
    ]

    if len(active_accounts) < 2:
        print("Not enough active accounts for warmup")
        return

    for from_email, from_account in active_accounts:
        # Calculate daily limit
        started_at = from_account.get("warmup_started_at", datetime.utcnow())
        days_active = (datetime.utcnow() - started_at).days
        daily_limit = warmup_manager.get_daily_limit(days_active)

        # Check if we've sent enough today
        today_sent = from_account.get("today_sent", 0)
        if today_sent >= daily_limit:
            continue

        # Pick a random recipient
        recipients = [
            (e, a) for e, a in active_accounts
            if e != from_email and a.get("is_active", False)
        ]

        if not recipients:
            continue

        to_email, to_account = random.choice(recipients)

        # Generate warmup ID and send
        warmup_id = warmup_manager.generate_warmup_id()

        success = await warmup_manager.send_warmup_email(
            from_account=from_account,
            to_email=to_email,
            warmup_id=warmup_id,
        )

        if success:
            from_account["total_sent"] = from_account.get("total_sent", 0) + 1
            from_account["today_sent"] = from_account.get("today_sent", 0) + 1
            print(f"Sent warmup email from {from_email} to {to_email}")

        # Add random delay between sends
        await asyncio.sleep(random.uniform(60, 300))  # 1-5 minutes


async def warmup_receive_task():
    """Check inboxes and process warmup emails."""
    print(f"[{datetime.utcnow()}] Running warmup receive task...")

    for email, account in warmup_manager.accounts.items():
        if not account.get("is_active", False):
            continue

        # Check inbox for warmup emails
        warmup_emails = await warmup_manager.check_inbox(account)

        for warmup_email in warmup_emails:
            account["total_received"] = account.get("total_received", 0) + 1

            # Move from spam if needed
            if warmup_email.get("in_spam"):
                success = await warmup_manager.move_to_inbox(
                    account, warmup_email["msg_id"]
                )
                if success:
                    account["spam_moves"] = account.get("spam_moves", 0) + 1
                    print(f"Moved email from spam for {email}")

            # Randomly reply (70% probability)
            if random.random() < settings.WARMUP_REPLY_PROBABILITY:
                # Add random delay
                delay = random.randint(
                    settings.WARMUP_MIN_REPLY_DELAY,
                    settings.WARMUP_MAX_REPLY_DELAY
                )
                await asyncio.sleep(delay)

                # Send reply
                success = await warmup_manager.send_reply(
                    account=account,
                    to_email=warmup_email.get("from_email", ""),
                    original_subject=warmup_email.get("subject", "Re:"),
                )

                if success:
                    account["total_replied"] = account.get("total_replied", 0) + 1
                    print(f"Sent reply from {email}")


async def reset_daily_counters():
    """Reset daily email counters at midnight."""
    print(f"[{datetime.utcnow()}] Resetting daily counters...")

    for email, account in warmup_manager.accounts.items():
        account["today_sent"] = 0


def run_worker():
    """Run the background worker."""
    print("Starting Lead Machine Worker...")

    # Create scheduler
    scheduler = AsyncIOScheduler()

    # Add warmup send job (every 30 minutes)
    scheduler.add_job(
        warmup_send_task,
        trigger=IntervalTrigger(minutes=30),
        id="warmup_send",
        name="Send warmup emails",
    )

    # Add warmup receive job (every 5 minutes)
    scheduler.add_job(
        warmup_receive_task,
        trigger=IntervalTrigger(minutes=5),
        id="warmup_receive",
        name="Check and process warmup emails",
    )

    # Add daily reset job (every 24 hours)
    scheduler.add_job(
        reset_daily_counters,
        trigger=IntervalTrigger(hours=24),
        id="reset_counters",
        name="Reset daily counters",
    )

    # Start scheduler
    scheduler.start()

    print("Worker started. Running scheduled tasks...")

    # Keep running
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down worker...")
        scheduler.shutdown()


if __name__ == "__main__":
    run_worker()
