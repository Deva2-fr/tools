"""Tâches planifiées : monitoring, veille CVE, synchro Outlook, rappels d'échéances."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services import (
    billing,
    digest,
    integrations,
    monitoring,
    outlook,
    qonto,
    renewals,
    security_watch,
    taxes,
)

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


@safe("facturation")
def job_billing(db):
    log.info("Relances de factures : %d", billing.send_reminders(db))


@safe("renouvellements")
def job_renewals(db):
    renewals.roll_renewals(db)
    log.info("Rappels de renouvellement : %d", renewals.send_reminders(db))


@safe("qonto")
def job_qonto(db):
    if qonto.is_configured(db):
        log.info("Qonto : %d nouvelle(s) transaction(s)", qonto.sync(db)["created"])


@safe("resume_quotidien")
def job_digest(db):
    digest.send(db)


def main():
    logging.basicConfig(level=logging.INFO)
    tz = get_settings().timezone
    sched = BlockingScheduler(timezone=tz)
    sched.add_job(job_monitoring, "interval", minutes=1, max_instances=1, coalesce=True)
    sched.add_job(job_mail, "interval", minutes=5, max_instances=1, coalesce=True)
    sched.add_job(job_qonto, "interval", hours=1, max_instances=1, coalesce=True)
    sched.add_job(job_cve, CronTrigger(hour=3, minute=15, timezone=tz))
    sched.add_job(job_taxes, CronTrigger(hour=8, minute=30, timezone=tz))
    sched.add_job(job_billing, CronTrigger(hour=8, minute=35, timezone=tz))
    sched.add_job(job_renewals, CronTrigger(hour=8, minute=40, timezone=tz))
    sched.add_job(job_digest, CronTrigger(hour=8, minute=50, timezone=tz))
    log.info("Worker démarré (fuseau %s)", tz)
    sched.start()


if __name__ == "__main__":
    main()
