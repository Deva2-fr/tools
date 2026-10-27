"""Tâches planifiées : monitoring, veille CVE, synchro Outlook, rappels d'échéances."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.services import integrations, monitoring, outlook, security_watch, taxes

log = logging.getLogger("deva2.worker")


def safe(name):
    """Une tâche qui plante ne doit jamais arrêter le planificateur."""

    def deco(fn):
        def wrapper():
            try:
                with SessionLocal() as db:
                    fn(db)
            except Exception:
                log.exception("Tâche %s en échec", name)

        wrapper.__name__ = name
        return wrapper

    return deco


@safe("monitoring")
def job_monitoring(db):
    n = monitoring.run_due_checks(db)
    if n:
        log.info("%d site(s) vérifié(s)", n)


@safe("veille_cve")
def job_cve(db):
    log.info("Veille CVE : %d nouvelle(s) alerte(s)", security_watch.scan_all(db))


@safe("outlook")
def job_mail(db):
    if integrations.get(db, "microsoft_refresh_token"):
        outlook.sync_inbox(db)


@safe("echeances")
def job_taxes(db):
    log.info("Rappels d'échéances envoyés : %d", taxes.send_reminders(db))


def main():
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(engine)
    tz = get_settings().timezone
    sched = BlockingScheduler(timezone=tz)
    sched.add_job(job_monitoring, "interval", minutes=1, max_instances=1, coalesce=True)
    sched.add_job(job_mail, "interval", minutes=5, max_instances=1, coalesce=True)
    sched.add_job(job_cve, CronTrigger(hour=3, minute=15, timezone=tz))
    sched.add_job(job_taxes, CronTrigger(hour=8, minute=30, timezone=tz))
    log.info("Worker démarré (fuseau %s)", tz)
    sched.start()


if __name__ == "__main__":
    main()
